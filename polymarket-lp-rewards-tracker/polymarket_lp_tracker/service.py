"""Service layer: turns raw client data into dashboard-ready payloads.

Combines three sources:
* the official Incentives API (programs + your earnings) — authoritative,
* your open maker orders + live order book — for current eligibility,
* the reward-scoring estimator — to rank live orders and draw the reward zone.
"""

from __future__ import annotations

from collections import defaultdict

from . import rewards
from .client import RealClient, TrackerClient
from .config import Settings, get_settings
from .demo import DemoClient


def build_client(settings: Settings) -> TrackerClient:
    if settings.live:
        return RealClient(settings)
    return DemoClient()


class TrackerService:
    def __init__(self, settings: Settings | None = None, client: TrackerClient | None = None):
        self.settings = settings or get_settings()
        self.client = client or build_client(self.settings)

    # ---- meta ------------------------------------------------------------
    def meta(self) -> dict:
        return {
            "mode": "demo" if self.settings.demo_mode else "live",
            "authenticated": bool(getattr(self.client, "authenticated", False)),
            "refresh_seconds": self.settings.refresh_seconds,
            "default_max_spread_cents": self.settings.default_max_spread_cents,
            "incentives_base_url": self.settings.incentives_base_url,
        }

    # ---- programs + live eligibility ------------------------------------
    def programs_view(self) -> dict:
        """Active incentive programs, each with reward zone + your live standing."""
        programs = self.client.get_incentive_programs(statuses=["active"])
        my_orders = self._orders_by_slug()
        max_spread = self.settings.default_program().max_spread

        rows = []
        for prog in programs:
            active = prog.active_periods() or prog.time_periods
            if not active:
                continue
            period = max(active, key=lambda p: p.reward_pool)
            book = self.client.get_book(prog.slug)
            mid = rewards.midpoint(book.best_bid, book.best_ask)
            # target_size is a *book-depth* target, not a per-order floor; the
            # per-order minimum comes from config.
            min_size = self.settings.default_min_size
            two_sided = self._two_sided(mid)

            mine = my_orders.get(prog.slug, {"bids": [], "asks": []})
            est = rewards.estimate_reward(
                maker_bids=mine["bids"],
                maker_asks=mine["asks"],
                book_bids=book.bids,
                book_asks=book.asks,
                best_bid=book.best_bid,
                best_ask=book.best_ask,
                min_size=min_size,
                max_spread=max_spread,
                daily_pool_usd=period.reward_pool,
                two_sided=two_sided,
            )
            rows.append(
                {
                    "slug": prog.slug,
                    "program_type": period.program_type,
                    "period": period.period,
                    "status": period.status,
                    "reward_pool": period.reward_pool,
                    "target_size": period.target_size,
                    "discount_factor": period.discount_factor,
                    "start": period.start,
                    "end": period.end,
                    "midpoint": mid,
                    "best_bid": book.best_bid,
                    "best_ask": book.best_ask,
                    "reward_zone": rewards.reward_zone(mid, max_spread),
                    "my_orders": len(mine["bids"]) + len(mine["asks"]),
                    "my_qualifies": est.qualifies,
                    "my_two_sided": est.bid_score > 0 and est.ask_score > 0,
                    "my_share": est.share,
                    "my_estimated_period_usd": est.estimated_daily_usd,
                }
            )
        rows.sort(key=lambda r: (r["my_estimated_period_usd"], r["reward_pool"]), reverse=True)
        return {"programs": rows, "count": len(rows)}

    # ---- my open orders --------------------------------------------------
    def orders_view(self) -> dict:
        orders = self.client.list_open_orders()
        programs = {p.slug: p for p in self.client.get_incentive_programs(statuses=["active"])}
        max_spread = self.settings.default_program().max_spread
        books: dict[str, object] = {}
        rows = []
        for o in orders:
            book = books.get(o.slug)
            if book is None:
                book = self.client.get_book(o.slug)
                books[o.slug] = book
            mid = rewards.midpoint(book.best_bid, book.best_ask)
            prog = programs.get(o.slug)
            min_size = self.settings.default_min_size
            spread = rewards.spread_from_mid(o.price, mid) if mid is not None else None
            qualifies = (
                mid is not None
                and rewards.order_qualifies(o.price, o.size, mid, min_size, max_spread)
            )
            score = rewards.order_score(o.price, o.size, mid, max_spread) if mid is not None else 0.0
            rows.append(
                {
                    "id": o.id,
                    "slug": o.slug,
                    "side": o.side,
                    "price": o.price,
                    "size": o.size,
                    "state": o.state,
                    "midpoint": mid,
                    "spread_cents": round(spread * 100, 3) if spread is not None else None,
                    "min_size": min_size,
                    "has_program": prog is not None,
                    "qualifies": qualifies,
                    "score": round(score, 4),
                    "reason": self._ineligibility_reason(o, mid, min_size, max_spread),
                }
            )
        rows.sort(key=lambda r: (r["qualifies"], r["score"]), reverse=True)
        eligible = sum(1 for r in rows if r["qualifies"])
        return {"orders": rows, "count": len(rows), "eligible": eligible}

    # ---- earnings --------------------------------------------------------
    def earnings_view(self, start_date: str | None = None, end_date: str | None = None) -> dict:
        rewards_rows = self.client.get_incentive_earnings(start_date=start_date, end_date=end_date)
        by_date_status: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        by_market: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        totals: dict[str, float] = defaultdict(float)
        for r in rewards_rows:
            by_date_status[r.date][r.status] += r.reward
            by_market[r.slug][r.status] += r.reward
            totals[r.status] += r.reward

        dates = sorted(by_date_status)
        series = [
            {
                "date": d,
                "paid": round(by_date_status[d].get("PAID", 0.0), 2),
                "pending": round(by_date_status[d].get("PENDING", 0.0), 2),
                "skipped": round(by_date_status[d].get("SKIPPED", 0.0), 2),
            }
            for d in dates
        ]
        cumulative = 0.0
        for pt in series:
            cumulative += pt["paid"] + pt["pending"]
            pt["cumulative"] = round(cumulative, 2)

        markets = [
            {
                "slug": slug,
                "paid": round(v.get("PAID", 0.0), 2),
                "pending": round(v.get("PENDING", 0.0), 2),
                "skipped": round(v.get("SKIPPED", 0.0), 2),
                "total": round(v.get("PAID", 0.0) + v.get("PENDING", 0.0), 2),
            }
            for slug, v in by_market.items()
        ]
        markets.sort(key=lambda m: m["total"], reverse=True)

        return {
            "series": series,
            "markets": markets,
            "totals": {
                "paid": round(totals.get("PAID", 0.0), 2),
                "pending": round(totals.get("PENDING", 0.0), 2),
                "skipped": round(totals.get("SKIPPED", 0.0), 2),
                "all": round(totals.get("PAID", 0.0) + totals.get("PENDING", 0.0), 2),
            },
            "row_count": len(rewards_rows),
            "authenticated": bool(getattr(self.client, "authenticated", False)),
        }

    def balances_view(self) -> dict:
        return {"balances": [b.dict() for b in self.client.get_balances()]}

    def summary(self) -> dict:
        earnings = self.earnings_view()
        programs = self.programs_view()
        orders = self.orders_view()
        balances = self.balances_view()
        return {
            "meta": self.meta(),
            "earnings_totals": earnings["totals"],
            "active_programs": programs["count"],
            "open_orders": orders["count"],
            "eligible_orders": orders["eligible"],
            "balances": balances["balances"],
        }

    # ---- helpers ---------------------------------------------------------
    def _orders_by_slug(self) -> dict[str, dict[str, list[tuple[float, float]]]]:
        grouped: dict[str, dict[str, list[tuple[float, float]]]] = defaultdict(
            lambda: {"bids": [], "asks": []}
        )
        for o in self.client.list_open_orders():
            key = "bids" if o.side == "bid" else "asks"
            grouped[o.slug][key].append((o.price, o.size))
        return grouped

    @staticmethod
    def _two_sided(mid: float | None) -> bool:
        """Two-sided incentives apply away from the price extremes."""
        if mid is None:
            return True
        return 0.10 <= mid <= 0.90

    def _ineligibility_reason(self, order, mid, min_size, max_spread) -> str:
        if mid is None:
            return "no midpoint (one-sided/empty book)"
        if order.size < min_size:
            return f"size {order.size:g} < min {min_size:g}"
        if rewards.spread_from_mid(order.price, mid) > max_spread:
            return f"outside reward zone (±{max_spread * 100:g}c)"
        return "eligible"
