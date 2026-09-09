# Matched-entry exit sensitivity study

This is a read-only diagnostic CLI, not a trading policy or promotion gate.
Run from the backend directory (or `/app` in a deployed worker containing it):

```sh
python scripts/check_matched_exit_replay.py --book strategy --days 7 --per-strategy 30
python scripts/check_matched_exit_replay.py --book consolidated --days 7 --trade-id 411
```

The report goes to stdout. PostgreSQL transactions are read-only with bounded
query/lock timeouts and released before replay computation. No API, scheduler,
database schema, orders, strategy settings, or saved learning reports are changed.

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

Results include fees/slippage but EXCLUDE actual funding: do not call these fully
net returns. Actual-trade funding cannot be copied to different holding paths.
Profit factor uses equal-notional trade returns; INR means retain recorded sizing.
Alternative positions may overlap, so this is not an executable account portfolio
and does not report account drawdown. Giveback includes costs and uses observed
closing-price MFE, not an intrabar or tick-perfect peak.

Before any promotion: obtain finer matching price evidence and funding coverage,
run paired out-of-sample tests and an executable portfolio drawdown simulation.
The CLI always reports `promotion_allowed: false`, even with 30+ paired trades.
