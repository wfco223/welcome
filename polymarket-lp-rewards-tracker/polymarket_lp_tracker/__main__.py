"""Run the dashboard: ``python -m polymarket_lp_tracker``."""

from __future__ import annotations

import uvicorn

from .config import get_settings


def main() -> None:
    s = get_settings()
    print(f"Polymarket US LP Rewards Tracker — mode={'demo' if s.demo_mode else 'live'}")
    print(f"Open http://{s.host}:{s.port}")
    uvicorn.run("polymarket_lp_tracker.server:app", host=s.host, port=s.port, reload=False)


if __name__ == "__main__":
    main()
