# Paper loss-protection implementation

Scope: paper trading only. No live exchange orders, automatic live promotion,
historical PNL rewrite, or retroactive resizing of open positions.

## New-entry risk budget

`EQUITY_RISK_V1` applies at the final execution boundary in both the consolidated
paper ledger and each isolated Strategy Paper ledger:

- Confidence 40 to below 60: budget 0.25% of that ledger's current equity.
- Confidence 60 to 100: budget 0.50% of that ledger's current equity.
- Stop distance is measured from the actual simulated fill, not the old plan.
- Budget includes round-trip fees, at least 0.10% adverse exit-slippage reserve,
  and funding reserve over the holding horizon (at least 0.01% per modeled
  eight-hour interval; larger observed absolute funding rates increase it).
- Notional = budget / estimated net stop-loss fraction, capped by the existing
  confidence-tier notional ceiling and available account margin. Wider stops
  reduce position size. Amounts are INR; contract reference prices remain USDT.
- Open-position equity uses execution-only quotes at most five seconds old.
  Missing/invalid quotes, incomplete equity or nonpositive capacity block entry.
- Account/strategy-book transaction reservations cover capacity checks and save.
  A hidden rollback/commit invalidates the reservation and prevents the fill.
- Lifetime realized PNL and current open positions come from one SQL valuation
  snapshot, so an exit committing between separate reads cannot double-count PNL.

Example: at equity INR200,000 and confidence60, the risk budget is INR1,000.
A 0.75% stop +0.15% fees +0.10% slippage +0.06% funding reserve gives an
approximately INR94,339 maximum notional, before margin constraints. This is an
estimated loss budget, **not a guaranteed loss ceiling** during gaps or outages.
Existing capital ceilings and disabled optional daily/open-trade caps are not
silently changed by this release.

## Entry/exit evidence and experiments

See [controlled experiments](market_move_controlled_experiments.md). New Market
Move entry-only and delayed-trailing candidates remain isolated and frozen.
The incumbent entry conditions and its immediate trailing remain available as
the control. Existing Regime Trend Entry candidate is retained, not duplicated.

New trades persist bounded entry/exit JSON: original plan, execution mark/fill,
timestamps, drift, profile/version, equity/risk sizing, actual stop at trigger,
trigger/fill price, costs and observed-only favorable/adverse excursions.
HOLD observations are aggregated, not written as per-second audit rows.
Legacy missing evidence stays unknown. A profitable protected stop is not an
initial-stop failure; a pre-T1 trailed stop can still be a net loss after fees.
Holding deadlines are evaluated before trailing-stop updates.

PNL and Strategy Paper history expose the evidence. Failed pagination hides
unverified rows and offers retry; bounded cached pages cannot masquerade as a
different page. Closed history is ordered by close time and ID with a matching
index. A failed DB query reports unavailable history, not a verified empty set.
Aggregate trade-return cards explicitly distinguish rolling 24h/7d/30d sums
from account returns and an IST calendar-day result; INR wallet totals remain
the monetary account view.

Watchlist/pipeline status now preserves returned failures/degradation. Required
monitor/risk failures block new execution; optional strategy failures do not
block unrelated strategies. Automatic scheduling and entry freshness windows
are retained, not widened to conceal stale evidence.

## Rollout and validation

Local validation on 2026-09-07: full backend suite **1,175 passed**;
frontend utility tests **19 passed**; Vite production build succeeded.
Risk schema inspection reuses its session connection; a one-slot pool regression
verifies that it neither requires a second checkout nor loses the transaction.
Synthetic Chrome checks cover delayed/failed pagination, retry, cancellation,
late responses, legacy audit evidence and stalled response-body timeout.
Migration tests preserve the locked baseline and match new columns/indexes to
the ORM; an actual Railway migration/deployment has not been performed here.

1. Apply the additive nullable migration before running code that reads the new
   columns: PostgreSQL `pg_20260907_exit_evidence`, SQL Server
   `x2p3q4r5s6t7`. The locked PostgreSQL baseline is preserved.
2. Deploy API, worker and frontend together; keep PAPER mode and live execution
   disabled. No bulk historical backfill or open-position rewrite is required.
3. Verify pipeline run outcomes, database latency and 1-second exit monitor
   health in Railway. A local fix does not prove the earlier production outage
   or stale feed has recovered.
4. Verify the first new trade in each book: actual fill, current equity, reduced
   INR notional, persisted policy, fresh quote timestamps, and exit evidence.
5. Collect at least 30 closed trades per verified strategy/version/policy cohort
   for diagnosis, then continue a fresh prospective validation window. Do not
   mix old fixed-risk trades into the new cohort or infer a guaranteed 55% win rate.

Deployment and production monitoring are separate follow-up steps. The code
does not promise to eliminate stop-losses or automatically enable real trading.
