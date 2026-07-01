"""Plain, SDK-independent data structures shared by clients and the service.

Keeping these decoupled from ``polymarket_us.types`` means the demo client and
the real client return the same shapes, and the service/frontend never depend on
SDK internals.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


def _f(x) -> float | None:
    """Parse a possibly-stringy numeric (SDK Amount.value is a str)."""
    if x is None:
        return None
    if isinstance(x, dict):  # SDK Amount -> {"value": "0.53", "currency": "USD"}
        x = x.get("value")
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


@dataclass
class Market:
    slug: str
    title: str
    outcome: str = ""
    event_slug: str = ""
    liquidity: float = 0.0
    volume: float = 0.0
    active: bool = True
    closed: bool = False

    def dict(self) -> dict:
        return asdict(self)


@dataclass
class Book:
    slug: str
    bids: list[tuple[float, float]] = field(default_factory=list)  # (price, size), best first
    asks: list[tuple[float, float]] = field(default_factory=list)
    best_bid: float | None = None
    best_ask: float | None = None
    last_trade: float | None = None

    def dict(self) -> dict:
        return {
            "slug": self.slug,
            "bids": [[p, s] for p, s in self.bids],
            "asks": [[p, s] for p, s in self.asks],
            "best_bid": self.best_bid,
            "best_ask": self.best_ask,
            "last_trade": self.last_trade,
        }


@dataclass
class OpenOrder:
    id: str
    slug: str
    side: str  # "bid" | "ask"
    price: float
    size: float  # remaining (leaves) quantity
    state: str = ""

    def dict(self) -> dict:
        return asdict(self)


@dataclass
class Activity:
    type: str
    slug: str = ""
    when: str = ""
    amount: float | None = None
    realized_pnl: float | None = None
    description: str = ""

    def dict(self) -> dict:
        return asdict(self)


@dataclass
class Balance:
    currency: str
    current: float = 0.0
    buying_power: float = 0.0
    open_orders: float = 0.0
    unsettled: float = 0.0

    def dict(self) -> dict:
        return asdict(self)


@dataclass
class TimePeriod:
    """One incentive period of a program (from GET /v1/incentives)."""

    program_id: str = ""
    program_type: str = ""  # e.g. "liquidityProgram"
    start: str = ""
    end: str = ""  # may be "" when a live program has no known end
    reward_pool: float = 0.0  # total USD pool for this period
    status: str = ""  # active | closed | pending
    discount_factor: float | None = None
    target_size: float | None = None  # min book size to qualify
    period: str = ""  # early | day_of | live | ...
    created_at: str = ""

    def dict(self) -> dict:
        return asdict(self)


@dataclass
class IncentiveProgram:
    """Programs for one market (from GET /v1/incentives)."""

    slug: str
    time_periods: list[TimePeriod] = field(default_factory=list)

    def active_periods(self) -> list[TimePeriod]:
        return [p for p in self.time_periods if p.status == "active"]

    def dict(self) -> dict:
        return {"slug": self.slug, "time_periods": [p.dict() for p in self.time_periods]}


@dataclass
class UserReward:
    """One earnings row (from GET /v1/incentives/earnings).

    A single (slug, date) may appear once per status; sum across statuses to get
    the day's total for a market.
    """

    reward: float = 0.0
    program_type: str = ""
    slug: str = ""
    date: str = ""  # YYYY-MM-DD, Eastern Time
    status: str = ""  # PAID | PENDING | SKIPPED

    def dict(self) -> dict:
        return asdict(self)
