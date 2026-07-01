"""FastAPI app: JSON API + static dashboard.

Run:  uvicorn polymarket_lp_tracker.server:app --reload
or:   python -m polymarket_lp_tracker
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .service import TrackerService

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="Polymarket US Liquidity Rewards Tracker", version="0.1.0")


def service() -> TrackerService:
    # Rebuild per request so config/credential changes are picked up on reload.
    return TrackerService(get_settings())


@app.get("/api/meta")
def api_meta():
    return service().meta()


@app.get("/api/summary")
def api_summary():
    return service().summary()


@app.get("/api/programs")
def api_programs():
    return service().programs_view()


@app.get("/api/orders")
def api_orders():
    return service().orders_view()


@app.get("/api/earnings")
def api_earnings(
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
):
    return service().earnings_view(start_date=start_date, end_date=end_date)


@app.get("/api/balances")
def api_balances():
    return service().balances_view()


@app.get("/api/health")
def api_health():
    return {"ok": True}


# ---- static dashboard ----------------------------------------------------
@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
