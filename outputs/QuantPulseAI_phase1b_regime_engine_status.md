# QuantPulseAI Phase 1B Regime Engine Status

Date: `2026-06-17`

## Status

Phase 1B has started with the v3 13-regime engine foundation and now includes scenario, contradiction, probability, and paper-trade fill/slippage coverage.

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
- Scenario engine with 4-path outcomes in `app/intelligence/scenario_engine.py`
- Scenario endpoint in `signals_api.py`
- Scenario payload embedded in trade-setup responses
- Contradiction engine in `app/intelligence/contradiction_engine.py`
- Contradiction endpoint in `signals_api.py`
- Contradiction payload embedded in signal and master-AI responses
- Probability engine in `app/intelligence/probability_engine.py`
- Probability endpoint in `signals_api.py`
- Probability payload embedded in signal and master-AI responses
- Feature quality profile with sentiment and correlation in `app/features/feature_quality_engine.py`
- Feature quality endpoint in `features_api.py`
- Feature quality now feeds current `ai-scores` calculations
- Master AI regime scoring now understands expanded bullish/bearish v3 regime names
- Paper-trade fill/slippage model for candidate execution and monitor exits

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
Ran 130 tests in 0.516s
OK
```

## Remaining Phase 1B Work

The regime engine foundation is now implemented, but Phase 1B is not complete.

Remaining required v3 intelligence work:

- Add richer transition audit storage as a dedicated table when database migration is scheduled.
- Add dashboard views for regime catalog, latest regime state, and transition history.
