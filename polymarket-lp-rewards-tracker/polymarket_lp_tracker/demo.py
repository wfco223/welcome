"""Demo client: deterministic synthetic data implementing ``TrackerClient``.

Lets the whole dashboard run with no credentials and no network — useful for
development, screenshots, and for exploring the UI before wiring live keys.
"""

from __future__ import annotations

import hashlib

from .models import (
    Activity,
    Balance,
    Book,
    IncentiveProgram,
    Market,
    OpenOrder,
    TimePeriod,
    UserReward,
)

_MARKETS = [
    ("will-btc-close-above-100k-2026", "Will BTC close above $100k in 2026?", 0.62),
    ("fed-cuts-rates-july-2026", "Fed cuts rates at July 2026 meeting?", 0.41),
    ("world-cup-2026-usa-wins", "USA wins the 2026 World Cup?", 0.08),
    ("us-govt-shutdown-2026", "US government shutdown before Oct 2026?", 0.33),
    ("openai-ipo-2026", "OpenAI files for IPO in 2026?", 0.19),
    ("spx-6500-eoy-2026", "S&P 500 above 6500 at 2026 year-end?", 0.55),
    ("eth-flips-btc-2026", "ETH market cap flips BTC in 2026?", 0.04),
    ("nba-lakers-title-2026", "Lakers win the 2026 NBA title?", 0.12),
]


def _rng(slug: str) -> float:
    """Deterministic pseudo-random in [0,1) seeded by slug."""
    h = hashlib.sha256(slug.encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


class DemoClient:
    authenticated = True  # demo exposes "private" synthetic data too

    def list_markets(self, limit: int) -> list[Market]:
        out = []
        for slug, title, mid in _MARKETS[:limit]:
            r = _rng(slug)
            out.append(
                Market(
                    slug=slug,
                    title=title,
                    outcome="Yes",
                    event_slug=slug.rsplit("-", 1)[0],
                    liquidity=round(20_000 + r * 180_000, 2),
                    volume=round(100_000 + r * 2_000_000, 2),
                )
            )
        return out

    def get_book(self, slug: str) -> Book:
        mid = next((m for s, _, m in _MARKETS if s == slug), 0.5)
        r = _rng(slug)
        # Tight-ish two-sided book around the mid, a few levels each side.
        half = 0.005 + r * 0.01  # inside spread
        bids, asks = [], []
        for i in range(5):
            bp = round(max(0.01, mid - half - i * 0.01), 3)
            ap = round(min(0.99, mid + half + i * 0.01), 3)
            size_b = round(200 + (r * 1000) * (1.0 - i * 0.15), 1)
            size_a = round(180 + ((1 - r) * 1000) * (1.0 - i * 0.15), 1)
            bids.append((bp, size_b))
            asks.append((ap, size_a))
        best_bid = bids[0][0]
        best_ask = asks[0][0]
        return Book(
            slug=slug,
            bids=bids,
            asks=asks,
            best_bid=best_bid,
            best_ask=best_ask,
            last_trade=round((best_bid + best_ask) / 2, 3),
        )

    def list_open_orders(self) -> list[OpenOrder]:
        # Maker resting on both sides of two markets, one-sided on a third.
        return [
            OpenOrder("ord-1", "will-btc-close-above-100k-2026", "bid", 0.615, 500, "NEW"),
            OpenOrder("ord-2", "will-btc-close-above-100k-2026", "ask", 0.626, 450, "PARTIALLY_FILLED"),
            OpenOrder("ord-3", "fed-cuts-rates-july-2026", "bid", 0.404, 800, "NEW"),
            OpenOrder("ord-4", "fed-cuts-rates-july-2026", "ask", 0.418, 300, "NEW"),
            OpenOrder("ord-5", "spx-6500-eoy-2026", "bid", 0.548, 250, "NEW"),  # one-sided
            OpenOrder("ord-6", "us-govt-shutdown-2026", "ask", 0.40, 50, "NEW"),  # below min_size
        ]

    def list_activities(self, limit: int) -> list[Activity]:
        acts = [
            Activity("TRADE", "will-btc-close-above-100k-2026", "2026-06-30T14:02:00Z", 305.0, 12.5, "500 @ 0.61"),
            Activity("TRADE", "fed-cuts-rates-july-2026", "2026-06-30T11:20:00Z", 121.2, -4.0, "300 @ 0.404"),
            Activity("ACCOUNT_DEPOSIT", "", "2026-06-29T09:00:00Z", 1000.0, None, "settled"),
            Activity("TRADE", "spx-6500-eoy-2026", "2026-06-28T16:45:00Z", 137.0, 8.0, "250 @ 0.548"),
            Activity("REFERRAL_BONUS", "", "2026-06-27T00:00:00Z", 25.0, None, "referral"),
        ]
        return acts[:limit]

    def get_balances(self) -> list[Balance]:
        return [Balance("USD", current=4235.18, buying_power=3010.50, open_orders=1224.68, unsettled=0.0)]

    def get_incentive_programs(
        self, symbols=None, statuses=None, page_size: int = 100
    ) -> list[IncentiveProgram]:
        # A liquidity program on the top handful of markets (mirrors /v1/incentives).
        progs: list[IncentiveProgram] = []
        for slug, _title, _mid in _MARKETS[:5]:
            r = _rng(slug)
            pool = round(1000 + r * 4000, 2)
            progs.append(
                IncentiveProgram(
                    slug=slug,
                    time_periods=[
                        TimePeriod(
                            program_id=f"{slug}-liq-live",
                            program_type="liquidityProgram",
                            start="2026-06-25T04:00:00Z",
                            end="",
                            reward_pool=pool,
                            status="active",
                            discount_factor=round(0.3 + r * 0.15, 2),
                            target_size=round(5000 + r * 15000, 0),
                            period="live",
                            created_at="2026-06-24T00:00:00Z",
                        )
                    ],
                )
            )
        if symbols:
            progs = [p for p in progs if p.slug in symbols]
        return progs

    def get_incentive_earnings(
        self, start_date=None, end_date=None, market_slug=None, program_type=None
    ) -> list[UserReward]:
        # Two weeks of daily rewards on two markets, with PAID + PENDING rows.
        base = [
            ("will-btc-close-above-100k-2026", 12.0),
            ("fed-cuts-rates-july-2026", 7.5),
        ]
        rows: list[UserReward] = []
        days = [f"2026-06-{d:02d}" for d in range(17, 31)]
        for slug, scale in base:
            for i, date in enumerate(days):
                r = _rng(f"{slug}{date}")
                paid = round(scale * (0.6 + r), 2)
                rows.append(UserReward(paid, "liquidityProgram", slug, date, "PAID"))
                if i >= len(days) - 2:  # most recent days still pending
                    rows[-1] = UserReward(paid, "liquidityProgram", slug, date, "PENDING")
        if market_slug:
            rows = [r for r in rows if r.slug == market_slug]
        if start_date:
            rows = [r for r in rows if r.date >= start_date]
        if end_date:
            rows = [r for r in rows if r.date <= end_date]
        return rows
