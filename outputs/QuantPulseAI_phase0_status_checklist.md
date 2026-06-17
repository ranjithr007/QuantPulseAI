# QuantPulseAI Phase 0 Status Checklist

Assessment date: 2026-06-15

## Phase 0 Goal

Make QuantPulseAI runnable, observable, and honest about data quality before Phase 1 intelligence expansion. Phase 0 is not feature-complete trading logic; it is the foundation that prevents misleading API responses, stale signals, hidden scheduler failures, and blank placeholder modules.

## Completed

- [x] Extracted and inspected the project archive.
- [x] Created implementation gap roadmap: `outputs/QuantPulseAI_implementation_gap_roadmap.md`.
- [x] Added environment-driven app config in `backend/app/config.py`.
- [x] Moved database URL construction out of hardcoded app constants.
- [x] Added `.env.example`.
- [x] Expanded `.gitignore` for Python, venv, cache, model artifacts, and frontend build folders.
- [x] Replaced empty `README.md` with setup, run, database, test, scheduler, and known-gap notes.
- [x] Added `backend/start_backend.ps1` to set safe dev environment defaults before Uvicorn.
- [x] Added `/health` and `/health/dependencies`.
- [x] Disabled scheduler by default for Phase 0.
- [x] Made scheduler startup safe when `apscheduler` is missing.
- [x] Added scheduler job registry and one-job-at-a-time scheduler configuration.
- [x] Added scheduler control endpoints:
  - `/scheduler/jobs`
  - `/scheduler/status`
  - `/scheduler/jobs/{job_id}/dry-run`
- [x] Fixed ML and prediction imports so missing ML dependencies do not block app startup.
- [x] Fixed `RiskEngine.analyze` class/instance call issue.
- [x] Fixed `fusion_ai_api.py` undefined service reference.
- [x] Added `RiskRepository.latest`.
- [x] Fixed `WAIT` trade-plan ATR crash.
- [x] Made risk engine safely reject `WAIT`/`HOLD` signals.
- [x] Added LONG/SHORT support to risk stop/target engines.
- [x] Replaced hardcoded `/signals/{symbol}` placeholder.
- [x] Made `/signals/{symbol}` compute current signal from latest candle and current inputs.
- [x] Added validation for LONG target > entry and SHORT target < entry.
- [x] Marked invalid historical signals as `historical_invalid`.
- [x] Added freshness metadata to DB-backed and computed responses.
- [x] Replaced first batch of blank API modules:
  - `market_api.py`
  - `regime_api.py`
  - `ai_scores_api.py`
  - `indicators_api.py`
  - `intelligence_api.py`
- [x] Added computed fallback for `/ai-scores/{symbol}` when `ai_scores` table has no rows.
- [x] Added lightweight implementations for core empty engines:
  - `TechnicalEngine`
  - `VolatilityEngine`
  - `DerivativeEngine`
  - `SentimentEngine`
  - `RegimeEngine`
  - `DrawdownEngine`
  - `ConfidenceEngine`
- [x] Added compatibility wrappers for engine imports where needed.
- [x] Implemented SMC/planner placeholder cleanup:
  - `LiquiditySweepEngine`
  - `OrderBlockEngine`
  - `InvalidationEngine`
- [x] Added invalidation rules to trade planner output.
- [x] Fixed `MarketPriceRepository` to use `candle_time` instead of nonexistent `timestamp`.
- [x] Fixed `MarketPriceService` to use `close_price` instead of nonexistent `close`.
- [x] Added Phase 0 smoke and guardrail tests.
- [x] Verified latest test suite: 31 tests passing.
- [x] Verified app import with project venv: `import ok QuantPulse AI v3.0`, 27 routes.

## Working API Baseline

- [x] `/`
- [x] `/health`
- [x] `/health/dependencies`
- [x] `/docs`
- [x] `/features/{symbol}`
- [x] `/orderflow/{symbol}`
- [x] `/smc/{symbol}`
- [x] `/signals/{symbol}`
- [x] `/master-ai-v2/{symbol}`
- [x] `/fusion-ai-v2/fusion/{symbol}`
- [x] `/risk/{symbol}`
- [x] `/market/{symbol}/candles`
- [x] `/regime/{symbol}`
- [x] `/ai-scores/{symbol}`
- [x] `/indicators/{symbol}`
- [x] `/intelligence/{symbol}/snapshot`
- [x] `/scheduler/jobs`
- [x] `/scheduler/status`
- [x] `/scheduler/jobs/{job_id}/dry-run`

## Remaining Phase 0 Work

- [ ] Run scheduler dry-run imports for every job:
  - `market`
  - `feature`
  - `orderflow`
  - `smc`
  - `heatmap`
  - `whales`
  - `whale_ai`
  - `intelligence`
  - `master_ai`
  - `quality`
  - `backtest`
  - `fusion`
  - `trade_plan`
  - `risk`
  - `ml_dataset`
  - `ml_label`
  - `memory`
- [ ] Execute one scheduler job at a time with `execute=true`, starting with `market`.
- [ ] Fix any job-specific runtime errors found during dry runs.
- [ ] Decide whether to recreate `backend/venv` cleanly as `.venv` or keep using `SETUPTOOLS_USE_DISTUTILS=stdlib`.
- [ ] Remove generated artifacts from the workspace/package after approval:
  - `.vs`
  - `backend/venv` if replaced by `.venv`
  - `__pycache__`
  - stray `.pyc.*` files in `backend/tests`
- [ ] Replace or intentionally retire remaining real blank modules:
  - `collectors/binances/orderbook_collector.py`
  - `ml/registry/model_registry.py`
  - `ml/training/model_trainer.py`
  - `ml/prediction/ml_prediction_service.py`
  - `database/models/regimes.py`
  - `database/models/signals.py`
  - `database/models/trades.py`
  - `dependencies.py`
- [ ] Leave empty package `__init__.py` files alone or add package docstrings if preferred.
- [ ] Add actual API integration tests once a clean local venv is stable.
- [ ] Add a simple database seed/sample-data script for local smoke testing.
- [ ] Add route-level manual test notes for BTCUSDT, ETHUSDT, XRPUSDT.

## Phase 0 Completion Gate

Phase 0 can be marked complete when all of the following are true:

- [ ] Backend starts from a clean terminal with `.\start_backend.ps1`.
- [ ] `/health`, `/docs`, and all core read APIs respond.
- [ ] Every core response that uses database time-series data includes freshness metadata.
- [ ] `/signals/{symbol}` and `/master-ai-v2/{symbol}` never present stale historical trade plans as current signals.
- [ ] LONG trade plans validate target > entry; SHORT trade plans validate target < entry.
- [ ] Scheduler can list jobs and dry-run import every job without crashing the API.
- [ ] At least `market`, `feature`, `orderflow`, `smc`, `fusion`, and `master_ai` jobs execute once manually without unhandled exceptions.
- [ ] No user-facing API endpoint returns hardcoded fake data.
- [ ] No real implementation module remains zero-byte unless it is deliberately documented as deferred.
- [ ] Test suite passes.

## Current Verification Commands

Run tests:

```powershell
$env:PYTHONPATH="C:\Users\Ranjith.Rallapalli\OneDrive\Documents\QuentPulseAI\QuantPulseAI\backend"
python -m unittest discover -s C:\Users\Ranjith.Rallapalli\OneDrive\Documents\QuentPulseAI\QuantPulseAI\backend\tests
```

Start backend:

```powershell
cd C:\Users\Ranjith.Rallapalli\OneDrive\Documents\QuentPulseAI\QuantPulseAI\backend
.\start_backend.ps1
```

Check scheduler dry-run:

```powershell
curl http://127.0.0.1:8000/scheduler/jobs
curl -X POST "http://127.0.0.1:8000/scheduler/jobs/market/dry-run"
curl -X POST "http://127.0.0.1:8000/scheduler/jobs/market/dry-run?execute=true"
```

Check core API freshness:

```powershell
curl "http://127.0.0.1:8000/signals/BTCUSDT?timeframe=5m&stale_after_seconds=900"
curl "http://127.0.0.1:8000/master-ai-v2/BTCUSDT?timeframe=5m&stale_after_seconds=900"
curl "http://127.0.0.1:8000/features/BTCUSDT?timeframe=5m&stale_after_seconds=900"
```
