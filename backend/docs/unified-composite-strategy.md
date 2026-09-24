# Unified Composite Strategy

This strategy combines the existing QuantPulse engines behind one configurable
decision contract. It is designed for manual review and automatic paper trading.
Live execution remains disabled until a separately approved validation gate passes.

## Execution modes

- `MANUAL_REVIEW`: produce a complete signal, reasons, entry, targets, stop, and
  risk size; require a user confirmation before any order request.
- `PAPER_AUTO`: apply the same gates automatically to the isolated strategy paper
  book. This is the default automatic mode.
- `LIVE_AUTO`: reserved and rejected by the current policy. It cannot be enabled
  by a per-coin profile or a UI toggle.

## Engine controls

Each coin has a profile. Every engine is independently `OFF`, `CONFIRM`, or
`REQUIRED`:

- technical trend and volatility;
- AI/master signal and confidence;
- orderflow and CVD;
- smart-money concepts (structure, liquidity, imbalance, order blocks);
- whale activity;
- funding rate and open-interest change;
- liquidation heatmap;
- volume and liquidity quality.

`REQUIRED` blocks an entry when the input is missing, stale, contradictory, or
opposite to the proposed direction. `CONFIRM` contributes evidence when fresh and
blocks only when it produces a high-severity contradiction. `OFF` is excluded and
is recorded in the decision audit. No missing input is silently treated as a
positive signal.

## Decision contract

1. Select a closed candle and verify freshness for every enabled engine.
2. Establish the direction from the technical/regime engine and master AI signal.
3. Require the configured confirmation count and reject high-severity conflicts
   from orderflow, SMC, derivatives, whale, liquidation, or volume context.
4. Calculate the entry, initial stop, Target 1, Target 2, and maximum holding time.
5. Apply the coin profile's risk fraction, daily loss limit, weekly loss limit,
   one-position-per-coin rule, and leverage cap.
6. Return `LONG`, `SHORT`, or `WAIT` with a structured explanation. A `WAIT` is
   the correct result when evidence is incomplete.

## Per-coin overrides

Profiles may override the following without changing strategy code:

- enabled engines and engine weights;
- allowed direction and timeframes;
- minimum confidence and confirmation count;
- entry mode (`market`, `pullback`, or `breakout-retest`);
- stop mode (`ATR`, `structure`, or fixed percentage) and ATR multiplier;
- Target 1/Target 2 reward-to-risk levels and partial-close fraction;
- trailing activation and protection rule;
- maximum hold time, slippage limit, risk per trade, leverage, and open-position cap.

Overrides are bounded by global safety limits. A coin profile cannot increase
leverage, risk, or loss limits beyond the global policy.

## Stop-loss analysis

Every stop exit records an analysis classification: wrong direction, insufficient
confirmation, stale or contradictory input, volatility/stop placement, execution
slippage, news or data gap, or unknown. The analysis may propose a new immutable
candidate, but it cannot change the active profile automatically. A candidate must
pass chronological walk-forward testing, costs/slippage modeling, an untouched
holdout, and minimum sample/profit-factor/drawdown gates before consideration.

## Capital protection

The strategy does not target a guaranteed win rate or daily return. A candidate is
rejected when expectancy is non-positive after fees and funding, profit factor is
below the validation threshold, drawdown exceeds policy, or evidence quality is
insufficient. The current default remains paper-only with live execution disabled.
