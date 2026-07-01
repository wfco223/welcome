# Polymarket US — Liquidity Rewards Tracker

A web dashboard that tracks **liquidity / market-maker incentive rewards** on
[Polymarket US](https://polymarket.us) (the CFTC-regulated US platform).

It combines three data sources:

| Source | Used for | Auth |
| ------ | -------- | ---- |
| **Incentives API** `GET /v1/incentives` | Active incentive programs, reward pools, periods, target size | Public |
| **Incentives API** `GET /v1/incentives/earnings` | Your actual **PAID / PENDING** rewards by market & date | API key |
| **Polymarket US SDK** (markets / book / orders / balances) | Live order book, your open maker orders, account balances | Public + API key |

From these it shows what you've earned, which programs are live, and — for your
resting maker orders — whether they currently sit inside the **reward zone** and
how strong they are, using a reward-scoring estimator.

> The Incentives API lives on its own host,
> `https://api.prod.polymarketexchange.com`, and is **not** wrapped by the public
> `polymarket-us` pip SDK, so this project calls it directly and signs the
> authenticated `earnings` call with the SDK's Ed25519 helper.

## Screenshot

Run it (see below) and open the dashboard — it works out of the box with
**synthetic demo data**, no credentials required.

## Features

- **Earnings over time** — daily PAID + PENDING bars with a cumulative line
  (`/v1/incentives/earnings`), plus a per-market breakdown.
- **Active incentive programs** — reward pool, period (`early`/`live`/…),
  target size, discount factor, live midpoint, computed reward zone, and your
  estimated share of the pool.
- **My open maker orders** — for each resting order: spread from midpoint,
  whether it qualifies (size ≥ min, inside the reward zone), a shape-weighted
  score, and a plain-English reason when it doesn't qualify.
- **Account balances** and summary cards.
- Auto-refreshing single-page dashboard (vanilla JS + Chart.js).
- **Demo mode** with deterministic synthetic data for offline exploration.

## What is estimated vs. authoritative

- **Authoritative** (straight from the Incentives API): your paid/pending USD,
  the list of programs, and their reward pools / periods / target sizes.
- **Estimated** (computed here from the public order book): midpoint, the reward
  zone, per-order eligibility, and your *share* of a pool. Polymarket's exact
  payout formula and constants are internal; the estimator reproduces the
  published shape (tighter spread + two-sided depth scores higher) so you can
  rank your own orders and see live standing. Every estimate is labelled in the
  UI. See [`rewards.py`](polymarket_lp_tracker/rewards.py) for the model.

## Quick start

```bash
cd polymarket-lp-rewards-tracker
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Runs in DEMO mode (synthetic data) — no keys needed:
python -m polymarket_lp_tracker
# open http://127.0.0.1:8000
```

### Live mode

1. Create API keys at <https://polymarket.us/developer> (Ed25519 `key_id` +
   base64 `secret_key`).
2. Copy `.env.example` to `.env` and fill in:

   ```env
   LPT_DEMO_MODE=false
   LPT_KEY_ID=your-key-id
   LPT_SECRET_KEY=your-base64-secret
   ```

3. `python -m polymarket_lp_tracker`

The public program data (`/v1/incentives`) loads even without keys; earnings,
orders and balances require them.

> **Note on running location:** Polymarket US is US-only. The international
> platform (`clob.polymarket.com`) has a *different* rewards API and is
> geoblocked from US IPs — this tracker targets **US** endpoints.

## Configuration

All settings are environment variables (prefix `LPT_`, or a `.env` file). See
[`.env.example`](.env.example). Notable ones:

| Var | Default | Meaning |
| --- | ------- | ------- |
| `LPT_DEMO_MODE` | `true` | Use synthetic data (auto-on when no credentials) |
| `LPT_KEY_ID` / `LPT_SECRET_KEY` | — | Polymarket US API credentials |
| `LPT_DEFAULT_MIN_SIZE` | `100` | Per-order minimum size to score (estimator) |
| `LPT_DEFAULT_MAX_SPREAD_CENTS` | `3` | Reward-zone half-width in cents (estimator) |
| `LPT_DEFAULT_DAILY_POOL_USD` | `100` | Fallback pool if a program has none |
| `LPT_REFRESH_SECONDS` | `30` | Dashboard auto-refresh interval |
| `LPT_HOST` / `LPT_PORT` | `127.0.0.1` / `8000` | Server bind |

Per-market overrides for the estimator's `min_size` / `max_spread_cents` /
`daily_pool_usd` can be placed in a `programs.json` file (see
`program_for()` in [`config.py`](polymarket_lp_tracker/config.py)):

```json
{
  "aec-nba-bos-nyk-2026-04-01": { "min_size": 200, "max_spread_cents": 2 }
}
```

## API endpoints (this app)

| Endpoint | Description |
| -------- | ----------- |
| `GET /api/summary` | Cards + totals + meta |
| `GET /api/earnings?start_date=&end_date=` | Earnings series, by-market, totals |
| `GET /api/programs` | Active programs with reward zone + your standing |
| `GET /api/orders` | Your open orders with eligibility |
| `GET /api/balances` | Account balances |
| `GET /api/meta` · `GET /api/health` | Mode/auth info · health check |

## Project layout

```
polymarket_lp_tracker/
  config.py     env-driven settings + per-market program overrides
  models.py     plain, SDK-independent data structures
  rewards.py    pure reward-scoring math (fully unit-tested)
  client.py     RealClient: SDK + direct Incentives API calls
  demo.py       DemoClient: deterministic synthetic data
  service.py    assembles dashboard payloads
  server.py     FastAPI JSON API + static dashboard
web/            index.html, styles.css, app.js
tests/          pytest suite for rewards + service
```

## Tests

```bash
pip install pytest
python -m pytest tests/ -q
```

## Disclaimer

Not affiliated with Polymarket. Estimated figures are informational only and are
not a guarantee of rewards. Verify against the official Incentives API and your
account statements.
