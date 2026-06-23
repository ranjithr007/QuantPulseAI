# QuantPulseAI

QuantPulseAI is a FastAPI and React crypto-market intelligence platform aligned to the QuantPulse AI v3 architecture documents. It currently supports a local, paper-only workflow from market ingestion and multi-timeframe analysis through risk approval, simulated execution, monitoring, and performance reporting.

## Current Phase

Phase 1 simulated-trading status: validated locally. Live exchange execution remains disabled.

The next product phase is strategy validation:

- Extend the Backtester V2 chronological execution kernel with historical signal replay.
- Replay historical intelligence, risk, and trade decisions without look-ahead.
- Add fees, slippage, equity curves, drawdown, Sharpe, and expectancy.
- Add walk-forward and regime-specific evaluation.
- Continue paper trading before considering any live execution.

Backtester V2 now includes an initial leakage-controlled walk-forward validator. It selects stop/target parameters on each training window and evaluates frozen parameters on the following non-overlapping test window. Both expanding and rolling training modes are supported.

## Project Layout

- `backend/app/main.py` - FastAPI application entrypoint.
- `backend/app/intelligence` - scenario, probability, contradiction, fusion, and multi-timeframe intelligence.
- `backend/app/regimes` - 13-regime classification and transition logic.
- `backend/app/paper_trading` - paper fills, lifecycle monitoring, and performance.
- `backend/app/backtesting` - Backtester V2 execution kernel and performance metrics.
- `backend/app/jobs` and `backend/app/scheduler` - ingestion and pipeline orchestration.
- `backend/alembic` - database migrations.
- `frontend/quantpulse-dashboard` - React/Vite/Tailwind dashboard.

## Environment Setup

Create a virtual environment outside source control:

```powershell
cd C:\Users\Ranjith.Rallapalli\OneDrive\Documents\QuentPulseAI\QuantPulseAI\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Copy the sample environment file and adjust values:

```powershell
cd C:\Users\Ranjith.Rallapalli\OneDrive\Documents\QuentPulseAI\QuantPulseAI
Copy-Item .env.example .env
```

The scheduler is disabled by default in Phase 0. Keep it disabled for development startup unless you have installed all scheduler/job dependencies and configured the database:

```powershell
$env:QUANTPULSE_START_SCHEDULER="false"
```

This prevents background jobs from starting while you are only testing API startup.

## Running The Backend

From `backend`:

```powershell
.\start_backend.ps1
```

If you launch `uvicorn` directly from the archived `backend\venv`, set this first to avoid a setuptools `.pth` warning caused by the extracted virtual environment:

```powershell
$env:SETUPTOOLS_USE_DISTUTILS="stdlib"
uvicorn app.main:app --reload
```

Useful endpoints:

- `GET /`
- `GET /health`
- `GET /health/dependencies`
- `GET /docs`
- `GET /backtest/summary`
- `GET /backtest/walk-forward`

## Database

By default, the app builds a SQL Server LocalDB URL using:

- `QUANTPULSE_SQLSERVER`
- `QUANTPULSE_DATABASE`
- `QUANTPULSE_SQL_DRIVER`
- `QUANTPULSE_SQL_TRUSTED_CONNECTION`

You can override the full SQLAlchemy URL with:

```powershell
$env:QUANTPULSE_DATABASE_URL="mssql+pyodbc://@(localdb)\MSSQLLocalDB/QuantPulseAI?driver=ODBC+Driver+17+for+SQL+Server&trusted_connection=yes"
```

Run migrations from `backend` after dependencies and the database driver are installed:

```powershell
alembic upgrade head
```

## Tests

Run the backend suite from `backend`:

```powershell
cd C:\Users\Ranjith.Rallapalli\OneDrive\Documents\QuentPulseAI\QuantPulseAI\backend
.\.venv\Scripts\python.exe -m pytest -q
```

Build the frontend from `frontend\quantpulse-dashboard`:

```powershell
npm install
npm run build
```

## Known Gaps

High-priority gaps:

- Backtester V2 currently runs a directional re-entry baseline; historical AI-signal replay and walk-forward orchestration are still required for strategy claims.
- Market/pipeline queries need performance work under the fallback database.
- Phase 1B intelligence needs historical calibration rather than more rule accumulation.
- ML registry, drift monitoring, model governance, portfolio risk, RBAC, audit hardening, and SRE remain future work.
- Live exchange execution is intentionally unavailable.

## Scheduler Dry Run

Keep the background scheduler disabled until individual jobs pass dry-run checks:

```powershell
$env:QUANTPULSE_START_SCHEDULER="false"
uvicorn app.main:app --reload
```

List available jobs:

```powershell
curl http://127.0.0.1:8000/scheduler/jobs
curl http://127.0.0.1:8000/scheduler/status
```

Validate a single job can be imported without executing it:

```powershell
curl -X POST "http://127.0.0.1:8000/scheduler/jobs/market/dry-run"
```

Run one selected job once:

```powershell
curl -X POST "http://127.0.0.1:8000/scheduler/jobs/market/dry-run?execute=true"
```

Only after dry runs are clean, enable the scheduler for one job:

```powershell
$env:QUANTPULSE_START_SCHEDULER="true"
$env:QUANTPULSE_SCHEDULER_JOBS="market"
.\start_backend.ps1
```

Automatic reload is opt-in because Windows reload subprocesses can generate repeated permission errors in some environments:

```powershell
.\start_backend.ps1 -Reload
```

The startup script archives legacy `backend-run.*.log` files once they exceed 25 MB. Change the threshold with `-MaxLegacyLogSizeMB`.

Use comma-separated job ids to add more jobs gradually, or `all` only after every job has passed dry-run validation.
