# QuantPulseAI Phase 1 Validation Checklist

Assessment date: 2026-06-17

## Phase 1 Goal

Validate the complete simulated trading workflow before alerts or live execution:

`watchlist` -> `trade_plans` -> `risk` -> `paper execution` -> `paper monitor` -> `performance` -> `pipeline status`

Phase 1 is successful when the system can repeatedly run this loop, report each stage clearly, avoid duplicate active trades, reject invalid setups, and never place real exchange orders.

## Required Startup

- [ ] Start backend from the project backend folder.

```powershell
cd C:\Users\Ranjith.Rallapalli\OneDrive\Documents\QuentPulseAI\QuantPulseAI\backend
.\start_backend.ps1
```

- [ ] Confirm API is running.

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" | ConvertTo-Json -Depth 10
Invoke-RestMethod -Uri "http://127.0.0.1:8000/docs"
```

Pass criteria:

- `/health` returns a healthy response.
- `/docs` opens in browser or returns Swagger HTML.

## Automated Test Gate

- [ ] Run backend tests.

```powershell
$env:PYTHONPATH="C:\Users\Ranjith.Rallapalli\OneDrive\Documents\QuentPulseAI\QuantPulseAI\backend"
python -m unittest discover -s C:\Users\Ranjith.Rallapalli\OneDrive\Documents\QuentPulseAI\QuantPulseAI\backend\tests
```

Pass criteria:

- Test suite exits successfully.
- Current expected count after Phase 1 pipeline work: `99` tests.

## Scheduler Job Registry

- [ ] Confirm required jobs are registered.

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/scheduler/jobs" | ConvertTo-Json -Depth 10
```

Required job ids:

- [ ] `market`
- [ ] `feature`
- [ ] `regime`
- [ ] `orderflow`
- [ ] `smc`
- [ ] `watchlist_persist`
- [ ] `risk`
- [ ] `paper_trade_execute`
- [ ] `paper_trade_monitor`
- [ ] `pipeline_cycle`

Pass criteria:

- All required jobs appear in the `jobs` list.
- `paper-trade-execute`, `paper-trade-monitor`, and `pipeline-cycle` work as hyphen aliases in dry-run URLs.

## Data Freshness Gate

- [ ] Confirm core signal APIs include freshness and are not presenting stale historical plans as current.

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/signals/BTCUSDT" | ConvertTo-Json -Depth 10
Invoke-RestMethod -Uri "http://127.0.0.1:8000/master-ai/BTCUSDT" | ConvertTo-Json -Depth 10
```

Pass criteria:

- Responses include `freshness`.
- Stale persisted signals appear under ignored/historical fields, not as current actionable signals.
- Any LONG plan has target greater than entry.
- Any SHORT plan has target less than entry.

## Watchlist Gate

- [ ] Check full watchlist.

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/signals/watchlist?mode=intraday" | ConvertTo-Json -Depth 10
```

- [ ] Check READY only.

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/signals/watchlist?mode=intraday&status=READY" | ConvertTo-Json -Depth 10
```

- [ ] Check near-ready setups.

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/signals/watchlist?mode=intraday&failed_max=1" | ConvertTo-Json -Depth 10
```

Pass criteria:

- Response includes `summary`, `filters`, `sort`, `count`, `total_count`, and `records`.
- READY setups appear before lower-priority setups.
- `failed_max=1` only returns rows with zero or one failed condition.
- `count=0` is acceptable when no market setup is ready, as long as the response is explicit.

## Multi-Timeframe Diagnostics Gate

- [ ] Check timeframe diagnostics.

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/signals/BTCUSDT/diagnostics?timeframe=5m" | ConvertTo-Json -Depth 10
Invoke-RestMethod -Uri "http://127.0.0.1:8000/signals/BTCUSDT/diagnostics?timeframe=15m" | ConvertTo-Json -Depth 10
Invoke-RestMethod -Uri "http://127.0.0.1:8000/signals/BTCUSDT/diagnostics?timeframe=1h" | ConvertTo-Json -Depth 10
```

- [ ] Check multi-timeframe confirmation.

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/signals/BTCUSDT/multi-timeframe?mode=intraday" | ConvertTo-Json -Depth 10
```

- [ ] Check entry trigger.

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/signals/BTCUSDT/entry-trigger?mode=intraday" | ConvertTo-Json -Depth 10
```

Pass criteria:

- Diagnostics show component scores and freshness.
- Multi-timeframe output shows overall bias and trade permission.
- Entry trigger clearly reports `READY`, `WAIT`, or blocked condition names.

## Persist READY Trade Plans

- [ ] Persist READY setups manually.

```powershell
Invoke-RestMethod -Method POST -Uri "http://127.0.0.1:8000/signals/watchlist/persist-ready?mode=intraday" | ConvertTo-Json -Depth 10
```

- [ ] Persist via scheduler dry-run.

```powershell
Invoke-RestMethod -Method POST -Uri "http://127.0.0.1:8000/scheduler/jobs/watchlist-persist/dry-run?execute=true" | ConvertTo-Json -Depth 10
```

Pass criteria:

- Response includes `saved_count` and `skipped_count`.
- Invalid or non-READY setups are skipped with a reason.
- Existing OPEN trade plans for the same `symbol + side` are skipped.
- `saved_count=0` is acceptable if no READY setup exists.

## Trade Plan Gate

- [ ] Check OPEN plans.

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/trade-plan/BTCUSDT?status=OPEN" | ConvertTo-Json -Depth 10
```

Pass criteria:

- OPEN plans show entry, stop, targets, risk reward, validation, and freshness.
- `count=0` is acceptable when no READY setup has been persisted.

## Risk Approval Gate

- [ ] Execute risk job.

```powershell
Invoke-RestMethod -Method POST -Uri "http://127.0.0.1:8000/scheduler/jobs/risk/dry-run?execute=true" | ConvertTo-Json -Depth 10
```

- [ ] Check latest risk for symbol.

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/risk/BTCUSDT" | ConvertTo-Json -Depth 10
```

Pass criteria:

- Risk job returns `EXECUTION_OK`.
- Result includes `trade_plans.processed`, `approved`, `rejected`, and `errors`.
- Valid persisted plans may produce `APPROVE`.
- Invalid plans produce `REJECT` and are not eligible for paper trading.
- `trade_plans.processed=0` is acceptable if there are no OPEN persisted plans.

## Paper-Trade Candidate Gate

- [ ] Check candidates.

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/paper-trade/candidates" | ConvertTo-Json -Depth 10
```

Pass criteria:

- Response includes `eligible_count`, `blocked_count`, and `records`.
- A candidate is eligible only when risk decision is `APPROVE`, fresh, newer than the plan, and price levels match.
- Blocked candidates include `blocked_reasons`.

## Paper-Trade Execution Gate

- [ ] Execute candidates manually.

```powershell
Invoke-RestMethod -Method POST -Uri "http://127.0.0.1:8000/paper-trade/execute-candidates" | ConvertTo-Json -Depth 10
```

- [ ] Execute candidates via scheduler dry-run.

```powershell
Invoke-RestMethod -Method POST -Uri "http://127.0.0.1:8000/scheduler/jobs/paper-trade-execute/dry-run?execute=true" | ConvertTo-Json -Depth 10
```

Pass criteria:

- Response source is `paper_trade_execution_simulator`.
- Eligible candidates create OPEN `paper_trades`.
- Duplicate OPEN paper trades for same `symbol + side` are skipped.
- No real exchange order is placed.

## Paper-Trade Monitor Gate

- [ ] Run monitor.

```powershell
Invoke-RestMethod -Method POST -Uri "http://127.0.0.1:8000/scheduler/jobs/paper-trade-monitor/dry-run?execute=true" | ConvertTo-Json -Depth 10
```

Pass criteria:

- Response returns `EXECUTION_OK`.
- OPEN paper trades stay open if neither stop nor target is hit.
- Trades close as `WIN` when target is hit.
- Trades close as `LOSS` when stop is hit.
- If stop and target are both hit in the same candle, result is conservatively `LOSS`.

## Paper-Trade Status Gate

- [ ] Check open simulated trades.

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/paper-trade/trades?status=OPEN" | ConvertTo-Json -Depth 10
```

- [ ] Check closed simulated trades.

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/paper-trade/trades?status=CLOSED" | ConvertTo-Json -Depth 10
```

Pass criteria:

- OPEN trades show entry, stop, target, position size, RR, risk percent, and opened time.
- CLOSED trades show exit price, result, PnL percent, and closed time.

## Performance Gate

- [ ] Check aggregate performance.

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/paper-trade/performance" | ConvertTo-Json -Depth 10
```

- [ ] Check symbol performance.

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/paper-trade/performance?symbol=BTCUSDT" | ConvertTo-Json -Depth 10
```

Pass criteria:

- Response includes total trades, open trades, closed trades, wins, losses, win rate, average PnL percent, and total PnL percent.
- Empty history returns zeros, not errors.

## Pipeline Status Gate

- [ ] Check pipeline control panel.

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/pipeline/status" | ConvertTo-Json -Depth 10
```

Pass criteria:

- Response source is `pipeline_status`.
- Response includes `status`, `blockers`, and `stages`.
- Stages include:
  - `watchlist`
  - `trade_plans`
  - `risk`
  - `paper_candidates`
  - `paper_trades`
  - `performance`
- `WAIT` status is acceptable when blockers are accurate.

## Full Pipeline Cycle Gate

- [ ] Dry-run import only.

```powershell
Invoke-RestMethod -Method POST -Uri "http://127.0.0.1:8000/scheduler/jobs/pipeline-cycle/dry-run" | ConvertTo-Json -Depth 10
```

- [ ] Execute full simulated cycle once.

```powershell
Invoke-RestMethod -Method POST -Uri "http://127.0.0.1:8000/scheduler/jobs/pipeline-cycle/dry-run?execute=true" | ConvertTo-Json -Depth 10
```

Pass criteria:

- Import-only returns `IMPORT_OK`.
- Execute returns `EXECUTION_OK`.
- Result source is `pipeline_cycle`.
- Stage order is:
  1. `watchlist_persist`
  2. `risk`
  3. `paper_trade_execute`
  4. `paper_trade_monitor`

## Acceptance Criteria

Phase 1 simulated pipeline can be marked valid when all are true:

- [ ] Backend starts cleanly.
- [ ] Test suite passes.
- [ ] Scheduler registry lists all required jobs.
- [ ] Watchlist returns honest READY/WAIT state with reasons and freshness.
- [ ] READY setups can be persisted or skipped with clear reasons.
- [ ] Risk job processes OPEN trade plans and saves APPROVE/REJECT decisions.
- [ ] Paper candidates only become eligible after matching fresh APPROVE risk.
- [ ] Paper execution creates simulated trades only, with duplicate protection.
- [ ] Paper monitor closes trades as WIN/LOSS based on latest candle.
- [ ] Paper-trade list and performance endpoints report the simulated portfolio.
- [ ] Pipeline status reports all stages and current blockers.
- [ ] Pipeline cycle dry-run executes without unhandled exceptions.

## Known Acceptable Waiting States

These are not failures:

- Watchlist has `READY=0` because market conditions are not aligned.
- Persist-ready returns `saved_count=0` because no READY setup exists.
- Risk job shows `trade_plans.processed=0` because no OPEN trade plans exist.
- Paper candidates show `eligible_count=0` because risk has not approved any OPEN plan.
- Paper performance returns zeros because no simulated trades have closed yet.

These are failures:

- API crash or unhandled traceback.
- Stale historical signal shown as current actionable signal.
- LONG target below entry or SHORT target above entry.
- Duplicate OPEN trade plan or duplicate OPEN paper trade for same `symbol + side`.
- Paper execution attempts any real exchange/order action.
- Pipeline status omits blockers when a stage has no actionable data.
