# All-strategy recorded decision replay

The Backtest page now automatically submits an independent comparison for the selected coin. Select a trailing 1, 7, 14 or 30-day window. Each registered base/active candidate version and each historical version found in that window gets its own row. Select the strategy name for ten-row paginated trade details (latest 100; summary metrics cover all closed replay trades).

This is **recorded decision replay**, not recomputation of current strategies against arbitrary historical inputs, nor out-of-sample proof. It never opens paper/live positions or changes strategy configuration. The existing automatic walk-forward panel remains unchanged.

## Execution

- POST `/api/backtest/strategy-comparison/jobs?symbol=ETHUSDT&days=7` uses the existing durable walk-forward queue, with an explicit engine discriminator. Production workers process it; all-in-one development has the existing background fallback. GET the returned status URL. Completed comparisons are cached for one hour. The page refreshes automatically.
- No migration is needed: existing decision snapshots, pipeline runs, market candles and walk-forward job tables are used.
- Independent INR 200,000 virtual portfolios, 85% unleveraged position notional, one position per strategy version/coin across 1h/2h/4h/1d. Different versions do not compete for capital. These are comparison assumptions, not a reproduction of shared-account admission controls.
- Use only recorded ELIGIBLE directional decisions, available before the entry bar and no older than ten minutes. Latest decisions replace older decisions per timeframe. Prefer the strongest recorded selected score. After exit a newer decision is required; same-side stop exits impose a thirty-minute cooldown, opposite-side signals remain eligible.
- Snapshot rows may have been updated by a subsequent generation. Availability is bounded by the later of creation, source/effective time and linked pipeline completion. Missing/pruned/uncompleted lineage is excluded. This cannot reconstruct overwritten snapshots; it is not a complete original decision tape.
- Enter at the next final verified 5m futures candle's open plus simulated slippage. Rebase recorded stop/target distances to the simulated fill. Missing/unsupported staged exit plans are skipped, not filled with current defaults.
- Use the paper exit evaluator: stop-first OHLC collisions, staged T1 fraction, T2, protection and favorable trailing. Stop changes apply to subsequent bars; same-bar T1/T2 settles both fractions without retrospectively testing a newly raised stop against an earlier low/high. Gap stops use the worse opening price. Time exits are enforced at candle granularity.
- Fees and fill slippage are included. Funding, historical FX movement, leverage and live tick-level sequencing are **not** modeled. PNL is INR virtual notional times the underlying return. Drawdown is realized-only. Profit factor is undefined when there are no losing trades.
- Use one price venue (largest verified coverage), never stitch multiple exchange candles. Missing candles while a trade is active censor it and stop that version's portfolio simulation. Open positions at the end are reported separately, not forcibly booked as closed gains/losses.
- A hard 60,000-row bound rejects overlarge input windows instead of silently truncating. Coverage, excluded decisions and fewer-than-30-trade warnings must be considered before comparing rows. No automatic ranking, optimization or live approval is produced.

For a full historical recomputation of every strategy, a future replay adapter must rebuild each version's inputs from an immutable, sufficiently complete historical feature/event archive (including spot, derivatives and macro inputs). This comparison deliberately does not fabricate that archive.
