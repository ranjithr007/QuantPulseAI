# QuantPulseAI Trading Invariants

This document contains governing trading rules for QuantPulseAI. These rules are
system invariants: production, paper-trading, backtesting, replay, scheduler, API,
and dashboard behavior must remain consistent with them. A code change must not
weaken or bypass an invariant without an explicit, version-controlled governance
decision.

## QP-TI-001: Multi-timeframe selection with one active trade per symbol

**Status:** Implemented for the paper-trading, governed signal, replay, and
backtest paths on 2026-08-11. Live execution remains independently disabled by
the R0 governance policy.

### Analysis universe

For every configured cryptocurrency symbol, the system must independently analyze
these canonical timeframes:

- `1h` — 1 hour
- `2h` — 2 hours
- `4h` — 4 hours
- `1d` — 1 day

Each timeframe must be evaluated independently and assigned exactly one current
market direction:

- `BULLISH`
- `BEARISH`
- `NEUTRAL`

The direction must be derived from the governed trading conditions and indicators
for that symbol and timeframe. Data from different timeframes may be compared when
selecting the best opportunity, but must not be mixed into an individual
timeframe's underlying regime calculation unless a separately governed rule
explicitly requires it.

### Entry selection

After all four timeframe evaluations are complete and fresh:

1. Reject `NEUTRAL` evaluations.
2. Apply all required entry, risk, freshness, contradiction, liquidity, and data
   quality gates to each `BULLISH` or `BEARISH` candidate.
3. Rank only the candidates that pass every required gate.
4. Select the strongest valid opportunity using the governed signal-ranking
   policy: validated risk confidence, signal confidence, reward/risk, timeframe
   durability (`1d` > `4h` > `2h` > `1h`), recency, then stable record id.
5. Map `BULLISH` to a Long candidate and `BEARISH` to a Short candidate.
6. Submit no order when no candidate passes every required gate.

Selection must be deterministic. If two candidates cannot be separated by the
governed ranking and tie-breaking policy, the safe result is no new trade.

### One-active-trade lock

There must be at most **one active trade per cryptocurrency symbol**, regardless
of entry timeframe, direction, strategy, or signal source.

The lock key is the normalized symbol (for example, `BTCUSDT`), not
`symbol + timeframe`. Before creating a trade, the execution path must atomically
verify that no active trade exists for that symbol. Concurrent signals must not be
able to create duplicate positions.

Example: while an active `BTCUSDT` Long entered from `1h` exists, QuantPulseAI must
not open another `BTCUSDT` trade from `2h`, `4h`, or `1d`, including a Short. Other
symbols may continue through their own independent selection cycles.

### Completion and rescan lifecycle

A symbol remains locked until its active trade reaches a terminal state through a
target, stop-loss, or another governed exit condition. The system must then:

1. Atomically mark the existing trade completed and release the symbol lock.
2. Start a new scan for that symbol across `1h`, `2h`, `4h`, and `1d`.
3. Recalculate each timeframe as `BULLISH`, `BEARISH`, or `NEUTRAL` from fresh,
   finalized market data.
4. Reapply every entry and risk gate.
5. Select the strongest valid opportunity.
6. Open at most one new trade, and only when all required entry conditions pass.

An old signal must not be queued for automatic execution after the prior trade
closes; the signal must be recalculated during the new scan.

### Canonical lifecycle

> Scan all timeframes -> determine direction -> select the best valid signal ->
> execute one trade per symbol -> wait for completion -> rescan all timeframes ->
> select the next opportunity.

### Required acceptance tests

Compliance requires automated coverage proving that:

- all four canonical timeframes are collected, finalized, and evaluated;
- each timeframe receives an independent direction;
- neutral and failed-gate candidates cannot create trades;
- the strongest valid candidate is selected deterministically;
- an active symbol cannot receive a second trade from any timeframe or direction;
- simultaneous requests cannot bypass the symbol lock;
- different symbols can each hold one active trade independently;
- target, stop-loss, and governed exits release the correct symbol lock;
- closing a trade triggers a fresh four-timeframe scan;
- stale pre-close signals are not executed after the lock is released;
- paper trading, backtesting, replay, and future live execution enforce the same
  invariant.

### Implementation record

The initial compatibility gap for `2h` was closed on 2026-08-11 across candle
collection, finality/freshness utilities, feature/regime/order-flow/SMC/fusion
jobs, governed signal APIs, replay/backtest contracts, and dashboard selectors.
The paper executor reduces eligible candidates to one winner per symbol. A
filtered unique database index on `paper_trades(symbol)` where `status = 'OPEN'`
enforces the symbol lock under concurrent requests. Closing a paper trade closes
or invalidates every queued plan for that symbol, and the deterministic pipeline
then rebuilds the four-timeframe state before executing another candidate.

Operational readiness is separate from code compliance. Every deployed database
must contain fresh, finalized candle coverage for all four canonical timeframes.
Missing timeframe data must produce an incomplete/neutral decision and must never
be silently replaced by another timeframe or mixed into that timeframe's regime.

For reporting, the four canonical timeframe directions are equally weighted:
each timeframe contributes 25 percentage points. Bullish, Bearish, Neutral, and
Unknown percentages are calculated as `direction count / 4 * 100`. This aggregate
percentage does not change any timeframe's regime or confidence. Regime confidence
is calculated independently by the selected rule for that single timeframe.
