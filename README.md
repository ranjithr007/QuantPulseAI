# QuantPulseAI

QuantPulseAI is a FastAPI and React crypto-market intelligence platform aligned to the QuantPulse AI v3 architecture documents. It currently supports a local, paper-only workflow from market ingestion and multi-timeframe analysis through risk approval, simulated execution, monitoring, and performance reporting.

## Governing Trading Invariants

Permanent application-level trading rules are recorded in
[`TRADING_INVARIANTS.md`](TRADING_INVARIANTS.md). In particular, QP-TI-001 governs
independent `1h`/`2h`/`4h`/`1d` analysis, strongest-valid-signal selection, and the
atomic one-active-trade-per-symbol requirement across all timeframes and trade
directions. Current behavior must not be described as compliant until its required
acceptance tests pass.

## Current Phase

Phase 1 simulated-trading status: validated locally. Live exchange execution remains disabled.

Extended paper-trading measurement is now available. New paper trades snapshot their mode,
entry timeframe, timeframe stack, regime, and simulated fee assumptions so performance can
be evaluated by cohort without reconstructing historical context.

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

### FRED macro context

The Market Move page can enrich its advisory macro score with verified data from
the Federal Reserve Economic Data (FRED) API. Create a FRED API key and provide
it only as a backend secret:

```text
FRED_API_KEY=<secret>
FRED_TIMEOUT_SECONDS=10
FRED_CACHE_SECONDS=1800
```

The collector uses Treasury yields, the broad US dollar index, Federal Reserve
balance-sheet liquidity, reverse repo, Treasury General Account, effective fed
funds, and VIX series. It reports `VERIFIED` only when the core series and at
least five total series are fresh. If the key or sufficient fresh data is
unavailable, macro context remains unavailable/degraded and cannot create a
trade signal. Even when verified, FRED is advisory confirmation capped at a
small contribution; the existing multi-timeframe direction, execution, and
risk rules remain authoritative.

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
- `GET /backtest/filtered-summary`
- `POST /backtest/walk-forward/jobs` (preferred; returns `202` immediately)
- `GET /backtest/walk-forward/jobs/{job_id}` (poll until completed or failed)
- `GET /backtest/walk-forward` (retired; returns `410` with the async submit URL)
- `GET /paper-trade/measurement`

The dashboard uses the queued walk-forward API. The replay runs after the submit
response has been released, so reverse-proxy timeouts do not terminate a valid
long-running calculation. Concurrent dashboard consumers with identical inputs
share one five-minute job/result instead of running duplicate replays. Job status
and completed results are stored durably in the canonical database.

Before treating a walk-forward result as Phase 2 evidence, verify the canonical
database contains sufficient finalized history for the selected symbol and all
four entry timeframes (`1h`, `2h`, `4h`, and `1d`). The API fix prevents HTTP 504;
it does not manufacture missing market history.

The governed, resumable history command is:

```powershell
cd backend
.\venv\Scripts\python.exe -m app.governance.candle_history_backfill --dry-run
.\venv\Scripts\python.exe -m app.governance.candle_history_backfill --days 550
```

For environments where network access and the application database run under
different identities, use `--export-cache <path.jsonl.gz>` in the download
context, followed by `--import-cache <path.jsonl.gz>` in the application context.
The importer is idempotent and supports MSSQL, PostgreSQL, and SQLite fallback.

`GET /regime/{symbol}/timeframe-summary` returns the latest independent regime,
direction, and regime confidence for `1h`, `2h`, `4h`, and `1d`. It also reports
aggregate direction percentages. Each canonical timeframe contributes exactly
25%; the aggregate is display/selection context and is never fed back into an
individual timeframe's regime calculation.

## Phase 2 Runtime Supervisor

Phase 2 evidence collection depends on LocalDB, the backend scheduler, and the
live-market service remaining available. On Windows, validate the supervisor
once from the repository root:

```powershell
.\backend\scripts\phase2_supervisor.ps1 -Once
```

Install the reversible per-user logon task:

```powershell
.\backend\scripts\install_phase2_supervisor.ps1
```

Remove it if required:

```powershell
.\backend\scripts\install_phase2_supervisor.ps1 -Uninstall
```

Runtime status and logs are written under `backend\runtime\`, which is excluded
from source control. The supervisor requires canonical MSSQL and will restart
the backend rather than permit Phase 2 collection into SQLite fallback.

## Cloud Runtime Roles

Cloud deployments must set `QUANTPULSE_ENV=production`, provide a canonical
`QUANTPULSE_DATABASE_URL`, and keep `QUANTPULSE_ALLOW_SQLITE_FALLBACK=false`.
The backend fails fast if the production database is unavailable instead of
writing Phase 2 evidence to temporary SQLite storage.

Use `QUANTPULSE_PROCESS_ROLE=api` for the public API process and
`QUANTPULSE_PROCESS_ROLE=worker` for the single scheduler process. Configure
the public dashboard origin through `QUANTPULSE_ALLOWED_ORIGINS`. Cloud HTTP
processes must bind `QUANTPULSE_HOST=0.0.0.0` and use the provider's `PORT`.

### Container deployment reference

`docker-compose.cloud.yml` defines four distinct deployment roles:

- `migrate`: one-shot `alembic upgrade head` release command.
- `api`: public FastAPI process with live-market WebSocket ownership.
- `worker`: singleton deterministic scheduler with no public port.
- `frontend`: Nginx-hosted production dashboard with SPA fallback routing.

Copy `cloud.env.example` to a secret-managed environment, replace every
placeholder, and validate the graph before deploying:

```powershell
docker compose --env-file cloud.env -f docker-compose.cloud.yml config
docker compose --env-file cloud.env -f docker-compose.cloud.yml build
docker compose --env-file cloud.env -f docker-compose.cloud.yml up
```

The migration image and command are packaged and import correctly. The target
cloud database is PostgreSQL. Do not run the historical SQL Server migration
chain unchanged against PostgreSQL; Railway deployment remains gated on the
reviewed PostgreSQL baseline described in
`outputs/postgresql_railway_readiness_audit_2026-08-09.md`. SQLite is not a
valid migration substitute.

### Production administrator authentication

All `POST`, `PUT`, `PATCH`, and `DELETE` requests require administrator
authentication when `QUANTPULSE_REQUIRE_ADMIN_AUTH=true`; production enables
this by default. API startup fails unless `QUANTPULSE_ADMIN_API_KEY` contains
at least 32 characters. Supply it through the provider's secret manager, never
through `VITE_*` variables or frontend source code.

Operators can authenticate with either header form:

```text
Authorization: Bearer <QUANTPULSE_ADMIN_API_KEY>
X-QuantPulse-Admin-Key: <QUANTPULSE_ADMIN_API_KEY>
```

The public dashboard may read market and evidence endpoints without this
secret. Mutating dashboard controls remain unavailable in a public deployment
until an authenticated operator-session UI is introduced.

### Production HTTP operations

Production enables per-client sliding-window rate limits by default: 120 read
requests and 30 mutating requests per minute. Configure these with
`QUANTPULSE_RATE_LIMIT_PER_MINUTE` and
`QUANTPULSE_ADMIN_RATE_LIMIT_PER_MINUTE`. Trusted cloud proxy addresses are
read from `X-Forwarded-For` only when `QUANTPULSE_TRUST_PROXY_HEADERS=true`.

Every response includes a request ID, clickjacking/MIME/referrer protections,
and an HSTS header in production. Request completion and unhandled exceptions
are emitted as single-line JSON logs without query strings or credentials.

Cloud probes:

- `/health/live` verifies that the HTTP process is alive.
- `/health/ready` verifies database connectivity and rejects non-canonical
  evidence storage in production.

## Database

The cloud target accepts Railway-style PostgreSQL URLs. Driver-neutral
`postgres://` and `postgresql://` values are normalized to psycopg 3:

```text
postgresql+psycopg://USER:PASSWORD@HOST:5432/railway?sslmode=require
```

The database-neutral runtime lives in `app.database.runtime`. The former
`app.database.sqlserver` module is a temporary compatibility shim during the
dual-dialect transition.

Local development continues to build a SQL Server LocalDB URL by default using:

- `QUANTPULSE_SQLSERVER`
- `QUANTPULSE_DATABASE`
- `QUANTPULSE_SQL_DRIVER`
- `QUANTPULSE_SQL_TRUSTED_CONNECTION`

You can override the full SQLAlchemy URL with:

```powershell
$env:QUANTPULSE_DATABASE_URL="mssql+pyodbc://@(localdb)\MSSQLLocalDB/QuantPulseAI?driver=ODBC+Driver+17+for+SQL+Server&trusted_connection=yes"
```

Run migrations from `backend` only against a database supported by the selected
migration baseline:

```powershell
alembic upgrade head
```

The extended paper-measurement migration adds nullable context and cost fields to existing
trade-plan and paper-trade tables. Existing records remain usable, but the measurement report
marks missing legacy context and fee snapshots as data-quality gaps.

## Extended Paper-Trading Measurement

The default evidence gate requires at least 100 closed trades observed over at least 90 days.
After evidence is sufficient, the report passes only when all profitability gates pass:

- Compounded net return is positive.
- Per-trade expectancy is positive.
- Profit factor is at least `1.30`.
- Maximum drawdown is no greater than `20%`.

Win rate is reported but deliberately is not a pass/fail gate. Simulated P&L for newly closed
paper trades includes adverse entry/exit slippage and a configurable round-trip fee snapshot.

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/paper-trade/measurement" |
    ConvertTo-Json -Depth 12
```

Thresholds can be overridden for diagnostics without changing stored results:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/paper-trade/measurement?min_closed_trades=100&min_observation_days=56&min_profit_factor=1.25&max_drawdown_percent=15" |
    ConvertTo-Json -Depth 12
```

The response includes overall metrics and cohort scorecards for symbol, side, mode, entry
timeframe, regime, and confidence band. A result remains `INSUFFICIENT_EVIDENCE` until both
the trade-count and observation-period gates are met, even if early results are profitable.

The default scheduler set now runs the paper-only evidence loop:

`market -> feature/regime/orderflow/SMC -> watchlist persistence -> risk -> paper execution -> paper monitoring`

`pipeline_cycle` is intentionally excluded from that set because it invokes the same paper
jobs sequentially and would duplicate work. Automation settings must remain in `PAPER` mode;
live execution is still unavailable.

## Filtered Historical Replay

`/backtest/summary` remains the constant-direction re-entry baseline. It is useful as a control,
but it is not an AI strategy claim. `/backtest/filtered-summary` reconstructs candle-derived
trend, momentum, volatility, liquidity, and regime state at each historical close. It applies
confidence and directional regime gates, enters at the next candle open, uses ATR-based stop
and target levels, permits one position at a time, and requires cooldown plus signal re-arming.

Historical SMC and order-flow snapshots currently cover only the live collection period, so the
filtered replay labels those inputs unavailable and must not be presented as full Master AI replay.

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
