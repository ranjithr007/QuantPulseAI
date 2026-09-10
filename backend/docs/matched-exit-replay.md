# Matched-entry exit sensitivity study

This is a read-only diagnostic CLI, not a trading policy or promotion gate.
Run from the backend directory (or `/app` in a deployed worker containing it):

```sh
python scripts/check_matched_exit_replay.py --book strategy --days 7 --per-strategy 30
python scripts/check_matched_exit_replay.py --book consolidated --days 7 --trade-id 411
python scripts/check_matched_exit_replay.py --book strategy --days 7 --per-strategy 30 --summary-only
python scripts/check_matched_exit_replay.py --book strategy --days 14 --per-strategy 100 --mature-only --summary-only
python scripts/check_matched_exit_replay.py --book strategy --days 14 --per-strategy 100 --mature-only --as-of 2026-09-10T03:15:10Z --summary-only
```

The report goes to stdout. PostgreSQL transactions are read-only with bounded
query/lock timeouts and released before replay computation. No API, scheduler,
database schema, orders, strategy settings, or saved learning reports are changed.
Use `--summary-only` for a compact terminal report: it retains selection coverage,
paired-trade counts, exclusions, assumptions and policy summaries, and omits only
the detailed per-trade rows. `trade_details_count` records how many rows were
omitted, and `trade_details_included` makes the output scope explicit.

## Research V2A cohort and costs

The V2A report is versioned as `matched_exit_sensitivity_v2a`. `--mature-only`
admits a record only when `opened_at + recorded max_hold_hours <= as_of`, before
the latest-per-strategy/version cap is applied. This is timestamp eligibility,
not outcome selection. `--as-of` freezes the UTC boundary for reproducibility.
The `cohort` object reports source, immature, unknown-maturity, eligible, selected
and path-complete counts separately.

Every exit leg is decomposed on the recorded entry-notional basis into signal
gross return, post-fill gross return, modeled entry slippage, modeled exit
slippage, recorded per-side fees, stored funding cost, and net return. The
post-fill identity must reconcile to zero apart from rounding. Planned and filled
prices are paper-model evidence, not actual exchange executions.

The CLI publishes 0/5/10/15bps exit-slippage sensitivity by default. Slippage
changes net return; it must never change the unslipped post-fill gross return.
Use `--exit-slippage-bps` to choose the detailed base scenario and
`--slippage-scenarios` to replace the comparison set.

Stored Binance funding events are matched to regular 00:00/08:00/16:00 UTC
slots for each alternative holding path. Events after T1 apply only to the
remaining position fraction. If an expected event is missing, after-funding
return is `null`, not zero; before-funding results remain available. Exceptional
venue funding-interval changes are not reconstructed by this version and must be
treated as a limitation.

Each selected entry is replayed independently with its recorded fill, initial stop,
targets, partial fraction, holding limit, fee rate and INR notional. Selection is
the latest entries per strategy/version BEFORE exclusions, including open trades;
it does not select winners or refill exclusions with more favourable samples.
Alternatives retain the complete original maximum-hold horizon, even after the
real trade closed. Missing, duplicate or invalid candles exclude the whole pair.

Alternatives: immediate trailing; delayed trailing at 1R; immediate trailing plus
an exploratory protection floor activated at a 1% favourable candle CLOSE,
locking half that move or modeled cost-covering break-even, whichever is tighter.
The candidate uses a 5bps funding reserve, not measured funding. Exit slippage is
fixed at 10bps for ALL alternatives; entry slippage is already in the saved fill.
These frozen exploratory constants are not an optimized recommendation.

Only verified/reconciled final Binance futures 5m candles are used. They are not
the live mark stream. Stops win same-bar collisions; updates apply next candle;
entry/deadline-overlap candles use close only and are flagged as ambiguous. A
deadline inside a candle is approximated by that candle's close (up to 5m late).
Exit timestamps are candle evidence bounds, not exact crossing timestamps.

Before-funding results include modeled fees/slippage. After-funding results exist
only for paths with complete stored funding slots; actual-trade funding is never
copied to a different alternative holding path.
Profit factor uses equal-notional trade returns; INR means retain recorded sizing.
Alternative positions may overlap, so this is not an executable account portfolio
and does not report account drawdown. Giveback includes costs and uses observed
closing-price MFE, not an intrabar or tick-perfect peak.

Before any promotion: obtain finer matching price evidence and funding coverage,
run paired out-of-sample tests and an executable portfolio drawdown simulation.
The CLI always reports `promotion_allowed: false`, even with 30+ paired trades.
