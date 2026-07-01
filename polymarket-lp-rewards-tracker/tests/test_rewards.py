"""Unit tests for the reward-scoring math and the demo-backed service."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from polymarket_lp_tracker import rewards  # noqa: E402
from polymarket_lp_tracker.config import Settings  # noqa: E402
from polymarket_lp_tracker.demo import DemoClient  # noqa: E402
from polymarket_lp_tracker.service import TrackerService  # noqa: E402


def test_midpoint():
    assert rewards.midpoint(0.60, 0.62) == 0.61
    assert rewards.midpoint(None, 0.5) is None
    assert rewards.midpoint(0.0, 0.5) is None


def test_order_qualifies_size_and_spread():
    mid, min_size, max_spread = 0.50, 100, 0.03
    assert rewards.order_qualifies(0.49, 200, mid, min_size, max_spread)
    assert not rewards.order_qualifies(0.49, 50, mid, min_size, max_spread)  # too small
    assert not rewards.order_qualifies(0.45, 200, mid, min_size, max_spread)  # too wide (5c > 3c)


def test_order_score_shape_decreases_with_spread():
    mid, max_spread = 0.50, 0.04
    at_mid = rewards.order_score(0.50, 100, mid, max_spread)
    near = rewards.order_score(0.49, 100, mid, max_spread)
    far = rewards.order_score(0.47, 100, mid, max_spread)
    outside = rewards.order_score(0.45, 100, mid, max_spread)
    assert at_mid > near > far > 0
    assert outside == 0.0
    # At the midpoint the shape factor is 1.0 -> score == size.
    assert abs(at_mid - 100) < 1e-9


def test_effective_score_rewards_two_sided():
    # Same total one-sided depth, but two-sided beats one-sided.
    one_sided = rewards.effective_score(200, 0, two_sided=True)
    two_sided = rewards.effective_score(100, 100, two_sided=True)
    assert two_sided > one_sided


def test_estimate_reward_share_and_usd():
    book_bids = [(0.49, 1000), (0.48, 1000)]
    book_asks = [(0.51, 1000), (0.52, 1000)]
    maker_bids = [(0.49, 500)]
    maker_asks = [(0.51, 500)]
    est = rewards.estimate_reward(
        maker_bids, maker_asks, book_bids, book_asks,
        best_bid=0.49, best_ask=0.51,
        min_size=100, max_spread=0.03, daily_pool_usd=100.0, two_sided=True,
    )
    assert est.midpoint == 0.50
    assert est.qualifies
    assert 0 < est.share <= 1
    assert est.estimated_daily_usd == est.share * 100.0


def test_estimate_reward_no_midpoint():
    est = rewards.estimate_reward([], [], [], [], None, None, 100, 0.03, 100.0)
    assert est.midpoint is None
    assert not est.qualifies
    assert est.estimated_daily_usd == 0.0


def test_reward_zone_clamped():
    z = rewards.reward_zone(0.98, 0.05)
    assert z["upper"] == 1.0  # clamped
    assert z["lower"] == 0.93


# ---- service integration on demo data -----------------------------------
def _demo_service():
    s = Settings(demo_mode=True)
    return TrackerService(settings=s, client=DemoClient())


def test_service_earnings_view():
    v = _demo_service().earnings_view()
    assert v["row_count"] > 0
    assert v["totals"]["paid"] > 0
    assert v["series"]  # time series present
    assert v["series"][-1]["cumulative"] >= v["series"][0]["cumulative"]


def test_service_programs_view():
    v = _demo_service().programs_view()
    assert v["count"] > 0
    top = v["programs"][0]
    assert "reward_pool" in top and "reward_zone" in top


def test_service_orders_view_flags_eligibility():
    v = _demo_service().orders_view()
    assert v["count"] > 0
    # The 50-share order (below min size) must be flagged ineligible.
    small = [o for o in v["orders"] if o["size"] == 50]
    assert small and not small[0]["qualifies"]


def test_service_summary():
    v = _demo_service().summary()
    assert v["meta"]["mode"] == "demo"
    assert v["active_programs"] >= 1
    assert v["open_orders"] >= 1
