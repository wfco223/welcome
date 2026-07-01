"""Liquidity-reward scoring math.

This module is a self-contained, side-effect-free estimator. It is used two ways:

1. As a *cross-check / fallback* for the on-chain reward numbers when the
   official Polymarket US Incentives API is not wired up (or when running the
   demo). It reproduces Polymarket's published liquidity-rewards model closely
   enough to answer "is my order eligible, and how strong is it?".
2. To visualise the *reward zone* around the midpoint on the dashboard.

It is NOT a claim about the exact USD you will be paid — Polymarket's authorative
per-user numbers come from the Incentives API. Every estimate here is labelled as
such in the UI.

Model (per Polymarket's liquidity-rewards documentation)
--------------------------------------------------------
For a market with midpoint ``m`` and a program with ``max_spread`` (distance from
the midpoint, in price units) and ``min_size`` (minimum resting size in shares):

* An order at price ``p`` with size ``q`` qualifies iff
  ``q >= min_size`` and ``spread = |p - m| <= max_spread``.
* Its score uses the documented shape function that rewards tighter spreads:

      S(spread) = ((max_spread - spread) / max_spread) ** 2 * q

* A maker's one-sided score for a side is the sum of ``S`` over their qualifying
  orders on that side. Because the program rewards *two-sided* depth, a maker's
  effective score over-weights the smaller (min) side:

      effective = 2 * min(Q_bid, Q_ask) + max(Q_bid, Q_ask)

  So for the same total depth, balanced two-sided liquidity scores strictly
  higher than one-sided (e.g. (100,100) -> 300 beats (200,0) -> 200). Markets
  where only one side is incentivised — very cheap / very expensive outcomes —
  set ``two_sided=False`` and the effective score is just ``Q_bid + Q_ask``.
* Estimated share of the daily pool is a maker's effective score divided by the
  total effective score of all resting liquidity in the book.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def midpoint(best_bid: float | None, best_ask: float | None) -> float | None:
    """Midpoint price, or None if the book is one-sided/empty."""
    if best_bid is None or best_ask is None:
        return None
    if best_bid <= 0 or best_ask <= 0:
        return None
    return (best_bid + best_ask) / 2.0


def spread_from_mid(price: float, mid: float) -> float:
    return abs(price - mid)


def order_qualifies(price: float, size: float, mid: float, min_size: float, max_spread: float) -> bool:
    if size < min_size:
        return False
    return spread_from_mid(price, mid) <= max_spread + 1e-12


def order_score(price: float, size: float, mid: float, max_spread: float) -> float:
    """Shape-weighted score for a single order. Zero if outside the reward zone.

    Note: the ``min_size`` gate is applied by the caller (``qualifies``) because
    aggregated book levels represent many orders and we score them by depth.
    """
    if max_spread <= 0:
        return 0.0
    s = spread_from_mid(price, mid)
    if s > max_spread:
        return 0.0
    shape = ((max_spread - s) / max_spread) ** 2
    return shape * size


@dataclass
class SideScore:
    """Aggregate qualifying score for one side of the book / one maker's side."""

    score: float = 0.0
    qualifying_size: float = 0.0
    order_count: int = 0
    levels: list[dict] = field(default_factory=list)


def score_levels(
    levels: list[tuple[float, float]],
    mid: float,
    min_size: float,
    max_spread: float,
) -> SideScore:
    """Score a list of (price, size) levels/orders on one side.

    ``min_size`` filters out levels/orders smaller than the program minimum.
    """
    out = SideScore()
    for price, size in levels:
        if size < min_size:
            continue
        s = spread_from_mid(price, mid)
        if s > max_spread + 1e-12:
            continue
        sc = order_score(price, size, mid, max_spread)
        if sc <= 0:
            continue
        out.score += sc
        out.qualifying_size += size
        out.order_count += 1
        out.levels.append(
            {
                "price": price,
                "size": size,
                "spread": s,
                "spread_cents": round(s * 100, 4),
                "score": sc,
            }
        )
    return out


def effective_score(q_bid: float, q_ask: float, two_sided: bool = True) -> float:
    """Combine per-side scores into a maker's effective reward score."""
    if not two_sided:
        return q_bid + q_ask
    # Reward two-sided depth: the smaller (min) side is over-weighted.
    return 2.0 * min(q_bid, q_ask) + max(q_bid, q_ask)


@dataclass
class RewardEstimate:
    midpoint: float | None
    qualifies: bool
    bid_score: float
    ask_score: float
    effective_score: float
    two_sided: bool
    market_total_score: float
    share: float
    estimated_daily_usd: float
    detail: dict = field(default_factory=dict)


def estimate_market_total(
    bid_levels: list[tuple[float, float]],
    ask_levels: list[tuple[float, float]],
    mid: float,
    min_size: float,
    max_spread: float,
    two_sided: bool = True,
) -> float:
    """Total effective score of all resting liquidity — the sharing denominator."""
    qb = score_levels(bid_levels, mid, min_size, max_spread).score
    qa = score_levels(ask_levels, mid, min_size, max_spread).score
    return effective_score(qb, qa, two_sided)


def estimate_reward(
    maker_bids: list[tuple[float, float]],
    maker_asks: list[tuple[float, float]],
    book_bids: list[tuple[float, float]],
    book_asks: list[tuple[float, float]],
    best_bid: float | None,
    best_ask: float | None,
    min_size: float,
    max_spread: float,
    daily_pool_usd: float,
    two_sided: bool = True,
) -> RewardEstimate:
    """Estimate a maker's qualifying score, pool share and daily USD.

    ``book_bids``/``book_asks`` should be the *full* aggregated book (which
    already includes the maker's own resting orders). ``maker_*`` are the maker's
    own orders.
    """
    mid = midpoint(best_bid, best_ask)
    if mid is None:
        return RewardEstimate(
            midpoint=None,
            qualifies=False,
            bid_score=0.0,
            ask_score=0.0,
            effective_score=0.0,
            two_sided=two_sided,
            market_total_score=0.0,
            share=0.0,
            estimated_daily_usd=0.0,
            detail={"reason": "no midpoint (one-sided or empty book)"},
        )

    maker_bid = score_levels(maker_bids, mid, min_size, max_spread)
    maker_ask = score_levels(maker_asks, mid, min_size, max_spread)
    maker_eff = effective_score(maker_bid.score, maker_ask.score, two_sided)

    total = estimate_market_total(book_bids, book_asks, mid, min_size, max_spread, two_sided)
    # The maker's own effective score is part of the book, so the denominator is
    # already inclusive. Guard against divide-by-zero.
    share = (maker_eff / total) if total > 0 else 0.0
    share = max(0.0, min(1.0, share))

    return RewardEstimate(
        midpoint=mid,
        qualifies=maker_eff > 0,
        bid_score=maker_bid.score,
        ask_score=maker_ask.score,
        effective_score=maker_eff,
        two_sided=two_sided,
        market_total_score=total,
        share=share,
        estimated_daily_usd=share * daily_pool_usd,
        detail={
            "bid": maker_bid.__dict__,
            "ask": maker_ask.__dict__,
            "one_sided_only": bool(maker_bid.score == 0) ^ bool(maker_ask.score == 0),
        },
    )


def reward_zone(mid: float | None, max_spread: float) -> dict | None:
    """Price band within which orders earn rewards, for UI overlays."""
    if mid is None:
        return None
    return {
        "midpoint": round(mid, 6),
        "lower": round(max(0.0, mid - max_spread), 6),
        "upper": round(min(1.0, mid + max_spread), 6),
        "max_spread": max_spread,
        "max_spread_cents": round(max_spread * 100, 4),
    }
