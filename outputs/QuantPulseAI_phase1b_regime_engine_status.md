# QuantPulseAI Phase 1B Regime Engine Status

Date: `2026-06-17`

## Status

Phase 1B has started with the v3 13-regime engine foundation.

Implemented:

- 13-regime catalog in `app/regimes/rules.py`
- Rule-based classification from existing feature inputs:
  - `TrendScore`
  - `MomentumScore`
  - `VolatilityScore`
  - `LiquidityScore`
  - `FinalScore`
- Hysteresis logic to avoid low-confidence regime flipping
- Dwell-cycle tracking
- Transition decision metadata:
  - `INITIAL`
  - `SAME`
  - `HELD_PREVIOUS`
  - `CONFIRMED_TRANSITION`
- JSON audit metadata persisted in `MarketRegimes.Reason`
- Scheduler job now returns execution summary
- Regime API catalog endpoint
- Regime API diagnostics endpoint
- Regime API summary endpoint
- Regime API transition-history endpoint
- Master AI regime scoring now understands expanded bullish/bearish v3 regime names

## Regime Catalog

Implemented regimes:

- `TRENDING_BULL`
- `TRENDING_BEAR`
- `BULL_PULLBACK`
- `BEAR_RALLY`
- `RANGE_ACCUMULATION`
- `RANGE_DISTRIBUTION`
- `RANGE_NEUTRAL`
- `HIGH_VOLATILITY_BREAKOUT`
- `HIGH_VOLATILITY_BREAKDOWN`
- `LOW_VOLATILITY_COMPRESSION`
- `LIQUIDITY_GRAB_BULLISH`
- `LIQUIDITY_GRAB_BEARISH`
- `MANIPULATION_PHASE`

## API Endpoints

Catalog:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/regime/catalog" | ConvertTo-Json -Depth 10
```

Diagnostics:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/regime/BTCUSDT/diagnostics?timeframe=5m&limit=5" | ConvertTo-Json -Depth 10
```

Scheduler dry-run:

```powershell
Invoke-RestMethod -Method POST -Uri "http://127.0.0.1:8000/scheduler/jobs/regime/dry-run?execute=true" | ConvertTo-Json -Depth 10
```

## Verification

Command:

```powershell
cd C:\Users\Ranjith.Rallapalli\OneDrive\Documents\QuentPulseAI\QuantPulseAI\backend
.\venv\Scripts\python.exe -m unittest discover -s tests
```

Result:

```text
Ran 113 tests in 0.419s
OK
```

## Remaining Phase 1B Work

The regime engine foundation is now implemented, but Phase 1B is not complete.

Remaining required v3 intelligence work:

- Add scenario engine with 4-path outcomes.
- Add probability/confidence engine with decay and Bayesian-style updates.
- Add contradiction engine.
- Expand features beyond the current score set.
- Add richer transition audit storage as a dedicated table when database migration is scheduled.
- Add dashboard views for regime catalog, latest regime state, and transition history.
