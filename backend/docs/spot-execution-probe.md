# Confidential — displayed execution-cost probe

`scripts/probe_spot_execution.py` makes only GET requests to the official public
market-data endpoint `https://data-api.binance.vision/api/v3/depth`. It has no
API-key, account or order functionality. It collects twelve rounds ten seconds
apart on BTC/ETH/SOL/XRP/BNB, up to 100 levels per side, then stops. It is not a
scheduled monitor and does not create an automation.

```powershell
.\venv\Scripts\python.exe scripts/probe_spot_execution.py --output outputs/spot_execution_probe/new_probe
.\venv\Scripts\python.exe -m pytest tests/test_spot_execution_probe.py -q
```

Each run preserves a plan with code hashes, raw responses, UTC request/receipt
timestamps, HTTP Date, local request duration, book update IDs, rejected samples
and a raw-log hash. Existing output directories are never overwritten. Rate or
access blocks stop the probe; an all-symbol connection failure stops early.
The initial sandbox network failure is retained as its own failed attempt.

For each of USDT 100/1,000/2,500, hypothetical base quantity = notional/midpoint.
The calculator walks displayed asks and bids for that SAME unrounded quantity.
Round-trip book cost is `(ask_quote_cost-bid_quote_proceeds)/mid_notional`.
Assumed round-trip fees are `(ask_quote_cost+bid_quote_proceeds)*fee_rate` divided
by the same mid-notional. They are estimates in quote-equivalent units. Partial
consumption of the last level is handled; inadequate depth is rejected rather
than extrapolated. Empty, nonfinite, unordered or crossed books are rejected.

Requests taking more than three seconds and nonincreasing/missing update IDs
are excluded. Eight distinct usable books per symbol is a basic acquisition
completeness check, not statistical adequacy. REST depth has no exchange event
timestamp: a recent local receive time cannot prove book freshness. Medians and
maximum observed costs describe only this brief sample; a maximum observed
value is not a worst-case execution bound.

The probe does not place orders, test fills, incorporate venue lot filters,
measure realized adverse selection, or establish typical/stressed liquidity.
The two sides are static hypothetical sweeps of the same snapshot, not a claim
that both transactions could fill in a changing market. No historical backtest
cost assumption should be reduced on this evidence alone.

Official references read on 2026-09-21:

- https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints
- https://developers.binance.com/docs/binance-spot-api-docs/faqs/market_data_only
