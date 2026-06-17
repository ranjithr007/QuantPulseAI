# QuantPulseAI

QuantPulseAI is a FastAPI-based crypto market intelligence prototype aligned to the QuantPulse AI v3 architecture documents. The current codebase is in Phase 0 stabilization: backend modules exist for market data, features, SMC/orderflow, risk, ML basics, jobs, and migrations, but the full institutional v3 platform is not complete yet.

## Current Phase

Phase 0 focus:

- Make the backend runnable from a clean checkout.
- Move local settings into environment variables.
- Add health/dependency endpoints.
- Wire intentionally available routers.
- Add smoke tests before expanding intelligence logic.
- Keep generated folders such as `.vs`, `backend/venv`, `__pycache__`, and local model artifacts out of source control.

## Project Layout

- `backend/app/main.py` - FastAPI application entrypoint.
- `backend/app/config.py` - environment-driven runtime settings.
- `backend/app/database/sqlserver.py` - SQLAlchemy SQL Server session setup.
- `backend/app/api` - API routers.
- `backend/app/jobs` - scheduled ingestion/engine jobs.
- `backend/app/database/models` - SQLAlchemy models.
- `backend/alembic` - database migrations.
- `frontend` - placeholder; no frontend implementation exists yet.

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

Run migrations from `backend` after dependencies and database driver are installed:

```powershell
alembic upgrade head
```

## Tests

The first Phase 0 tests are static smoke tests that avoid external dependencies:

```powershell
cd C:\Users\Ranjith.Rallapalli\OneDrive\Documents\QuentPulseAI\QuantPulseAI
python -m unittest discover -s backend\tests
```

Once backend dependencies are installed, add API-level tests that import `app.main` with `QUANTPULSE_START_SCHEDULER=false`.

## Known Gaps

See the implementation roadmap:

`C:\Users\Ranjith.Rallapalli\OneDrive\Documents\QuentPulseAI\outputs\QuantPulseAI_implementation_gap_roadmap.md`

High-priority gaps:

- Frontend is not implemented.
- Several backend modules are still placeholders.
- No paper trading ledger exists yet.
- The v3 13-regime state machine is not complete.
- Thesis, scenario, probability, contradiction, feature store, digital twin, XAI, governance, SRE, enterprise security, and AI agent layers remain future work.

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

Use comma-separated job ids to add more jobs gradually, or `all` only after every job has passed dry-run validation.
