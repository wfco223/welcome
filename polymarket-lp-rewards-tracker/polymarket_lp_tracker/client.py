"""Real Polymarket US client.

Thin wrapper over the official ``polymarket-us`` SDK that normalizes responses
into the plain models in :mod:`.models`, so the service layer never touches SDK
internals. Private data (orders, activities, balances, incentives) requires API
credentials; public data (markets, book) does not.

The official Incentives API lives on its own host
(``https://api.prod.polymarketexchange.com``) and is not wrapped by the SDK, so
it is called directly with httpx:

    GET /v1/incentives           (public)  -> programs + reward pools
    GET /v1/incentives/earnings  (auth)    -> the user's paid/pending rewards

Auth reuses the SDK's Ed25519 signing helper (``create_auth_headers``), which
signs ``timestamp+method+path`` and is host-independent.
"""

from __future__ import annotations

import logging
from typing import Protocol

import httpx

from .config import Settings
from .models import (
    Activity,
    Balance,
    Book,
    IncentiveProgram,
    Market,
    OpenOrder,
    TimePeriod,
    UserReward,
    _f,
)

log = logging.getLogger(__name__)


class TrackerClient(Protocol):
    """Interface implemented by both the real and demo clients."""

    def list_markets(self, limit: int) -> list[Market]: ...
    def get_book(self, slug: str) -> Book: ...
    def list_open_orders(self) -> list[OpenOrder]: ...
    def list_activities(self, limit: int) -> list[Activity]: ...
    def get_balances(self) -> list[Balance]: ...
    def get_incentive_programs(
        self, symbols: list[str] | None = None, statuses: list[str] | None = None, page_size: int = 100
    ) -> list[IncentiveProgram]: ...
    def get_incentive_earnings(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        market_slug: str | None = None,
        program_type: str | None = None,
    ) -> list[UserReward]: ...
    @property
    def authenticated(self) -> bool: ...


def _side_from_order(side: str) -> str:
    return "bid" if str(side).upper().endswith("BUY") else "ask"


class RealClient:
    """Wraps ``polymarket_us.PolymarketUS``."""

    def __init__(self, settings: Settings):
        from polymarket_us import PolymarketUS  # imported lazily so demo needs no network

        self.settings = settings
        self._sdk = PolymarketUS(
            key_id=settings.key_id or None,
            secret_key=settings.secret_key or None,
            gateway_base_url=settings.gateway_base_url,
            api_base_url=settings.api_base_url,
        )
        # Separate HTTP client for the Incentives API (different host).
        self._inc = httpx.Client(base_url=settings.incentives_base_url, timeout=30.0)

    @property
    def authenticated(self) -> bool:
        return self.settings.has_credentials

    # ---- public data -----------------------------------------------------
    def list_markets(self, limit: int) -> list[Market]:
        params = {"active": True, "closed": False, "limit": limit}
        resp = self._sdk.markets.list(params) or {}
        out: list[Market] = []
        for m in (resp.get("markets") or [])[:limit]:
            out.append(
                Market(
                    slug=m.get("slug", ""),
                    title=m.get("title", m.get("slug", "")),
                    outcome=m.get("outcome", ""),
                    event_slug=m.get("eventSlug", ""),
                    liquidity=float(m.get("liquidity", 0) or 0),
                    volume=float(m.get("volume", 0) or 0),
                    active=bool(m.get("active", True)),
                    closed=bool(m.get("closed", False)),
                )
            )
        return out

    def get_book(self, slug: str) -> Book:
        raw = self._sdk.markets.book(slug) or {}
        bids = [(_f(l.get("px")), _f(l.get("qty"))) for l in (raw.get("bids") or [])]
        asks = [(_f(l.get("px")), _f(l.get("qty"))) for l in (raw.get("offers") or [])]
        bids = [(p, s) for p, s in bids if p is not None and s]
        asks = [(p, s) for p, s in asks if p is not None and s]
        bids.sort(key=lambda x: x[0], reverse=True)  # best (highest) first
        asks.sort(key=lambda x: x[0])  # best (lowest) first
        best_bid = bids[0][0] if bids else None
        best_ask = asks[0][0] if asks else None
        last = None
        stats = raw.get("stats") or {}
        if stats.get("lastTradePx"):
            last = _f(stats.get("lastTradePx"))
        if best_bid is None or best_ask is None:
            # fall back to the dedicated BBO endpoint
            try:
                bbo = self._sdk.markets.bbo(slug) or {}
                best_bid = best_bid if best_bid is not None else _f(bbo.get("bestBid"))
                best_ask = best_ask if best_ask is not None else _f(bbo.get("bestAsk"))
                last = last if last is not None else _f(bbo.get("lastTradePx"))
            except Exception as e:  # noqa: BLE001
                log.debug("bbo fallback failed for %s: %s", slug, e)
        return Book(slug=slug, bids=bids, asks=asks, best_bid=best_bid, best_ask=best_ask, last_trade=last)

    # ---- private data ----------------------------------------------------
    def list_open_orders(self) -> list[OpenOrder]:
        if not self.authenticated:
            return []
        resp = self._sdk.orders.list() or {}
        out: list[OpenOrder] = []
        for o in resp.get("orders") or []:
            size = o.get("leavesQuantity") or o.get("quantity") or 0
            out.append(
                OpenOrder(
                    id=o.get("id", ""),
                    slug=o.get("marketSlug", "") or (o.get("marketMetadata") or {}).get("slug", ""),
                    side=_side_from_order(o.get("side", "")),
                    price=_f(o.get("price")) or 0.0,
                    size=float(size or 0),
                    state=str(o.get("state", "")).replace("ORDER_STATE_", ""),
                )
            )
        return out

    def list_activities(self, limit: int) -> list[Activity]:
        if not self.authenticated:
            return []
        resp = self._sdk.portfolio.activities({"limit": limit}) or {}
        out: list[Activity] = []
        for a in resp.get("activities") or []:
            atype = str(a.get("type", "")).replace("ACTIVITY_TYPE_", "")
            if a.get("trade"):
                t = a["trade"]
                out.append(
                    Activity(
                        type=atype or "TRADE",
                        slug=t.get("marketSlug", ""),
                        when=t.get("createTime", ""),
                        amount=_f(t.get("costBasis")),
                        realized_pnl=_f(t.get("realizedPnl")),
                        description=f"{t.get('qty','')} @ {_f(t.get('price'))}",
                    )
                )
            elif a.get("accountBalanceChange"):
                for tx in (a["accountBalanceChange"].get("transactions") or []):
                    out.append(
                        Activity(
                            type=atype,
                            when=tx.get("createTime", ""),
                            amount=_f(tx.get("amount")),
                            description=tx.get("status", ""),
                        )
                    )
            else:
                out.append(Activity(type=atype, when="", description=json.dumps(a)[:120]))
        return out

    def get_balances(self) -> list[Balance]:
        if not self.authenticated:
            return []
        resp = self._sdk.account.balances() or {}
        out: list[Balance] = []
        for b in resp.get("balances") or []:
            out.append(
                Balance(
                    currency=b.get("currency", "USD"),
                    current=float(b.get("currentBalance", 0) or 0),
                    buying_power=float(b.get("buyingPower", 0) or 0),
                    open_orders=float(b.get("openOrders", 0) or 0),
                    unsettled=float(b.get("unsettledFunds", 0) or 0),
                )
            )
        return out

    # ---- official incentives API -----------------------------------------
    def get_incentive_programs(
        self, symbols: list[str] | None = None, statuses: list[str] | None = None, page_size: int = 100
    ) -> list[IncentiveProgram]:
        """GET /v1/incentives (public) — programs and reward pools per market."""
        params: dict = {"pageSize": page_size}
        if symbols:
            params["symbols"] = symbols
        if statuses:
            params["statuses"] = statuses
        programs: list[IncentiveProgram] = []
        token: str | None = None
        for _ in range(20):  # bounded pagination
            if token:
                params["pageToken"] = token
            try:
                resp = self._inc.get("/v1/incentives", params=params)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:  # noqa: BLE001
                log.warning("GET /v1/incentives failed: %s", e)
                break
            programs.extend(_map_programs(data))
            token = data.get("nextPageToken")
            if not token:
                break
        return programs

    def get_incentive_earnings(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        market_slug: str | None = None,
        program_type: str | None = None,
    ) -> list[UserReward]:
        """GET /v1/incentives/earnings (auth) — the user's reward rows."""
        if not self.authenticated:
            return []
        path = "/v1/incentives/earnings"
        params: dict = {"startDate": start_date or self.settings.earnings_start_date}
        if end_date:
            params["endDate"] = end_date
        if market_slug:
            params["marketSlug"] = market_slug
        if program_type:
            params["programType"] = program_type
        try:
            from polymarket_us.auth import create_auth_headers

            headers = create_auth_headers(self.settings.key_id, self.settings.secret_key, "GET", path)
            resp = self._inc.get(path, params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:  # noqa: BLE001
            log.warning("GET %s failed: %s", path, e)
            return []
        return _map_rewards(data)


def _map_programs(data: dict) -> list[IncentiveProgram]:
    out: list[IncentiveProgram] = []
    for p in (data or {}).get("programs") or []:
        periods = []
        for tp in p.get("timePeriods") or []:
            periods.append(
                TimePeriod(
                    program_id=tp.get("programId", ""),
                    program_type=tp.get("programType", ""),
                    start=tp.get("start", ""),
                    end=tp.get("end", ""),
                    reward_pool=float(tp.get("rewardPool", 0) or 0),
                    status=tp.get("status", ""),
                    discount_factor=_f(tp.get("discountFactor")),
                    target_size=_f(tp.get("targetSize")),
                    period=tp.get("period", ""),
                    created_at=tp.get("createdAt", ""),
                )
            )
        out.append(IncentiveProgram(slug=p.get("marketSlug", ""), time_periods=periods))
    return out


def _map_rewards(data: dict) -> list[UserReward]:
    out: list[UserReward] = []
    for r in (data or {}).get("rewards") or []:
        out.append(
            UserReward(
                reward=float(r.get("reward", 0) or 0),
                program_type=r.get("programType", ""),
                slug=r.get("marketSlug", ""),
                date=r.get("date", ""),
                status=r.get("status", ""),
            )
        )
    return out
