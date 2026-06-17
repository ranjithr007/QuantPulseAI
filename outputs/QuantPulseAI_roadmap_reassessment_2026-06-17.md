# QuantPulseAI Roadmap Reassessment

Assessment date: 2026-06-17

## Executive Summary

The original roadmap from 2026-06-15 correctly identified QuantPulseAI as a partial backend prototype. Since then, the project has made major progress in Phase 0 stabilization and Phase 1 simulated-trading workflow.

Current status:

- Phase 0 foundation: largely complete for backend/API work.
- Phase 1 simulated trading loop: implemented as an MVP and ready for repeated validation.
- Phase 1 full v3 intelligence scope: still partial.
- Live trading readiness: not ready.
- Institutional v3 readiness: still far from complete.

The biggest change is that paper trading is no longer missing. The backend now has a safe simulated pipeline:

`watchlist` -> `trade_plans` -> `risk` -> `paper execution` -> `paper monitor` -> `performance` -> `pipeline status`

## Roadmap Status Changes

| Area | Original Status | Current Status | Notes |
|---|---|---|---|
| Backend startup/API foundation | Major blocker | Mostly complete | Routers are wired, health/docs work, scheduler dry-run exists. |
| Tests | Missing | Implemented | Current suite has 99 tests after Phase 1 pipeline work. |
| Scheduler control | Missing/partial | Implemented | Job registry, dry-run endpoint, hyphen aliases, pipeline cycle job. |
| Signal correctness | Placeholder/stale risk | Improved | Computed current signals, freshness, invalid historical signal handling. |
| Multi-timeframe intelligence | Missing | MVP implemented | 5m/15m/1h diagnostics, bias, permission, entry trigger. |
| Watchlist | Missing | MVP implemented | Filters, summary, priority sorting, failed condition filtering. |
| Trade plan persistence | Missing | MVP implemented | READY setups persist to `trade_plans` with duplicate guard. |
| Risk approval for persisted plans | Missing | MVP implemented | OPEN trade plans can be APPROVE/REJECT through risk job. |
| Paper trading | Missing | MVP implemented | Candidate gate, simulated execution, monitor, list, performance. |
| Pipeline observability | Missing | MVP implemented | `/pipeline/status` and `pipeline-cycle` scheduler job. |
| Frontend | Missing | Still missing | Should remain deferred until backend validation is stable. |
| 13-regime engine | Major gap | Still major gap | Current regime logic is not full v3 coverage. |
| Scenario/probability/contradiction engines | Missing | Still missing | Required for full v3 Phase 1 intelligence, not required for current simulated pipeline MVP. |
| Backtesting validation | Partial | Still partial | Simple backtest exists, but not walk-forward/acceptance metrics. |
| ML registry/governance | Partial/missing | Still partial/missing | Still Phase 3 work. |
| Security/compliance/SRE | Missing | Still missing | Still later-phase institutional hardening. |

## Phase 0 Evaluation

Phase 0 backend stabilization is effectively complete for the current working scope.

Completed:

- Environment-driven configuration and startup documentation.
- Health/dependency endpoints.
- Scheduler registry and dry-run API.
- Core routers wired into `main.py`.
- Placeholder API modules replaced for core read paths.
- Signal freshness and stale historical signal handling.
- Trade direction validation.
- Guardrail test suite.
- Phase 0 status checklist.

Still worth cleaning later:

- Generated/runtime artifacts such as old venv/cache folders.
- Remaining placeholder/deferred ML modules.
- Proper migration workflow for newly added tables.
- Broader API integration tests using a stable local test database.

Verdict:

- Phase 0 can be treated as complete enough to proceed, but not perfectly packaged.

## Phase 1 Evaluation

Phase 1 should now be split into two tracks:

1. **Phase 1A: Simulated Trading Pipeline MVP**
2. **Phase 1B: Full v3 Intelligence Coverage**

### Phase 1A: Simulated Trading Pipeline MVP

Status: implemented, pending repeated validation.

Implemented:

- `/signals/watchlist`
- `/signals/{symbol}/diagnostics`
- `/signals/{symbol}/multi-timeframe`
- `/signals/{symbol}/trade-setup`
- `/signals/{symbol}/entry-trigger`
- `/signals/watchlist/persist-ready`
- `watchlist_persist` scheduler job
- risk approval for persisted trade plans
- `/paper-trade/candidates`
- `/paper-trade/execute-candidates`
- `paper_trade_execute` scheduler job
- `paper_trade_monitor` scheduler job
- `/paper-trade/trades`
- `/paper-trade/performance`
- `/pipeline/status`
- `pipeline_cycle` scheduler job
- Phase 1 validation checklist

Remaining validation:

- Run the Phase 1 validation checklist end to end.
- Confirm `pipeline-cycle` repeatedly returns `EXECUTION_OK`.
- Confirm behavior when there are READY setups and when there are none.
- Confirm duplicate OPEN trade plan and duplicate OPEN paper trade protection.
- Confirm paper monitor closes WIN/LOSS correctly with real candles.

Verdict:

- Phase 1A is ready for operational validation.

### Phase 1B: Full v3 Intelligence Coverage

Status: not complete.

Still required from original v3 Phase 1 scope:

- Full 13-regime engine with hysteresis, dwell cycles, transition confidence, and audit records.
- Dedicated scenario engine with 4-path outcomes.
- Probability engine with Bayesian updates/confidence decay.
- Contradiction engine for invalidation, OI/funding conflict, CVD divergence, volatility break, and whale-flow conflict.
- More complete feature extraction, including correlation and sentiment.
- Production-grade market data ingestion with retry/rate-limit handling across required venues.
- Better slippage/fill assumptions for paper trading.
- Frontend MVP dashboard.

Verdict:

- Phase 1B remains the next major engineering block after validating Phase 1A.

## Recommended Updated Roadmap

### Now: Phase 1A Validation

Goal: prove the simulated backend pipeline is repeatable and safe.

Required:

- Run `outputs/QuantPulseAI_phase1_validation_checklist.md`.
- Record pass/fail outputs.
- Fix runtime failures found during validation.
- Keep live execution disabled.

Exit gate:

- Tests pass.
- `/pipeline/status` works.
- `pipeline-cycle` dry-run executes without unhandled exception.
- Paper trade lifecycle can be observed from candidate to performance.

### Next: Phase 1B Intelligence Completion

Goal: improve signal quality before alerts/live execution.

Recommended order:

1. Full regime engine.
2. Scenario engine.
3. Contradiction engine.
4. Probability/confidence engine.
5. Feature quality expansion.
6. Paper trading fill/slippage assumptions.
7. Frontend dashboard.

### Then: Phase 2 Validation and Backtesting

Goal: prove or reject the strategy.

Required:

- Walk-forward backtesting.
- Win rate, reward/risk, drawdown, profit factor, Sharpe.
- Regime-specific performance.
- Scenario prediction accuracy.
- Paper trading history report.
- Alerting for data quality, risk state, and candidate readiness.

### Later: Phase 3+ Hardening

Goal: move toward production-grade intelligence/execution.

Required:

- ML registry/training governance.
- Model cards and drift checks.
- Execution abstraction.
- Portfolio-level risk.
- Security, RBAC, audit trail, secrets management.
- SRE dashboards and alerts.

## Updated Immediate Priorities

1. Run Phase 1 validation checklist.
2. Fix any `pipeline-cycle` runtime failures.
3. Add a validation results log document.
4. Implement proper migration for `paper_trades`.
5. Add API integration tests against a test database.
6. Start Phase 1B with full regime engine.

## Updated Readiness

- Backend API readiness: good for local validation.
- Scheduler readiness: good for dry-run/manual local operation.
- Paper trading readiness: MVP implemented, validation required.
- Signal intelligence readiness: partial.
- Backtesting readiness: partial.
- Frontend readiness: missing.
- Live trading readiness: not ready.
- Institutional v3 readiness: not ready.
