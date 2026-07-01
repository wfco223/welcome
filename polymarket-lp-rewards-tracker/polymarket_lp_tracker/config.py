"""Application configuration, driven by environment / .env file.

The Polymarket US API does not expose liquidity-reward program parameters
(minimum order size, max spread, daily pool), so they are configured here with
sensible defaults and optional per-market overrides loaded from a JSON file.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class RewardProgram:
    """Reward-program parameters for a single market.

    Spread is stored internally in *price units* (dollars, 0..1) but configured
    in cents for convenience (Polymarket quotes max spread in cents).
    """

    def __init__(self, min_size: float, max_spread_cents: float, daily_pool_usd: float):
        self.min_size = float(min_size)
        self.max_spread_cents = float(max_spread_cents)
        self.daily_pool_usd = float(daily_pool_usd)

    @property
    def max_spread(self) -> float:
        """Max distance from midpoint in price units (e.g. 3 cents -> 0.03)."""
        return self.max_spread_cents / 100.0

    def as_dict(self) -> dict:
        return {
            "min_size": self.min_size,
            "max_spread_cents": self.max_spread_cents,
            "max_spread": self.max_spread,
            "daily_pool_usd": self.daily_pool_usd,
        }


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LPT_",
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Mode / credentials
    demo_mode: bool = True
    key_id: str = ""
    secret_key: str = ""
    gateway_base_url: str = "https://gateway.polymarket.us"
    api_base_url: str = "https://api.polymarket.us"

    # Default program parameters
    default_min_size: float = 100.0
    default_max_spread_cents: float = 3.0
    default_daily_pool_usd: float = 100.0

    # Behaviour
    market_scan_limit: int = 25
    refresh_seconds: int = 30

    # Official Incentives API. It lives on its own host (not api.polymarket.us)
    # and is not wrapped by the pip SDK, so we call it directly:
    #   GET /v1/incentives           (public)   -> programs + reward pools
    #   GET /v1/incentives/earnings  (auth)      -> your paid/pending rewards
    # Auth reuses the SDK's Ed25519 signing (X-PM-Access-Key/Timestamp/Signature).
    incentives_base_url: str = "https://api.prod.polymarketexchange.com"
    # Earliest date the earnings endpoint serves (its documented default).
    earnings_start_date: str = "2026-03-21"

    # Server
    host: str = "127.0.0.1"
    port: int = 8000

    # Path to per-market program overrides.
    programs_file: str = str(PROJECT_ROOT / "programs.json")

    @property
    def has_credentials(self) -> bool:
        return bool(self.key_id and self.secret_key)

    @property
    def live(self) -> bool:
        """Live mode requires demo disabled. Credentials unlock private data."""
        return not self.demo_mode

    def default_program(self) -> RewardProgram:
        return RewardProgram(
            self.default_min_size,
            self.default_max_spread_cents,
            self.default_daily_pool_usd,
        )

    @lru_cache(maxsize=1)
    def _overrides(self) -> dict[str, dict]:
        path = Path(self.programs_file)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    def program_for(self, market_slug: str) -> RewardProgram:
        """Resolve program parameters for a market, applying overrides."""
        base = self.default_program()
        ov = self._overrides().get(market_slug)
        if not ov:
            return base
        return RewardProgram(
            ov.get("min_size", base.min_size),
            ov.get("max_spread_cents", base.max_spread_cents),
            ov.get("daily_pool_usd", base.daily_pool_usd),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()
    # If no credentials were supplied, force demo mode regardless of the flag so
    # the app is always runnable out of the box.
    if not s.has_credentials and not s.demo_mode:
        object.__setattr__(s, "demo_mode", True)
    return s
