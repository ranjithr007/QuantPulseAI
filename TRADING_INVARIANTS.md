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

For paper trading, the absolute signal score must be at least **40**. Scores from
`+40` through `<+60` produce a minimum-tier Long, while scores from `-40`
through `>-60` produce a minimum-tier Short. The minimum tier risks at most
**0.5%** of account capital. Scores from `+60` through `+100` and from `-60`
through `-100` produce a full-size directional candidate using the configured
maximum risk per trade, currently **1.0%**. A configured maximum below `0.5%`
remains the absolute cap for every tier. Scores strictly between `-40` and `+40`
remain `WAIT` and cannot execute.

Multi-timeframe analysis must not subtract a numeric penalty from signal
confidence. Timeframe availability, direction, and confirmation remain separate
eligibility gates and may block a candidate. This threshold does not bypass
direction, reward/risk, timeframe confirmation, freshness, risk, or the
one-active-trade lock.

Every configured cryptocurrency on each official paper-entry timeframe uses one
staged exit policy measured from the actual paper entry price: **0.75% stop-loss**,
**1.5% Target 1**, and **2.3% Target 2**. Target 1 closes 50% of the position and
moves the remaining stop to the entry price. Target 2 closes the remaining 50%.
Any remainder still open after **48 hours** must close using the governed paper
fill model. The target engine must continue estimating adverse entry/exit
slippage and the configured **0.15% round-trip transaction fee** (`7.5` basis
points per side). Target 2 is the reward level used by the minimum 2:1 net
reward/risk approval guard. Funding is charged from actual funding events when
paper P&L is closed and reported separately.

The 48-hour exit is a safety deadline and must not depend exclusively on a new
database candle arriving. If the normal 5-minute replay has no new finalized
candle, the monitor must use a finalized post-deadline database candle or a
fresh Binance Futures mark price to close the paper position. If neither is
available, the monitor must fail visibly and block new execution rather than
silently leaving the overdue position open.

Selection must be deterministic. If two candidates cannot be separated by the
governed ranking and tie-breaking policy, the safe result is no new trade.

### One-active-trade lock

There must be at most **one active trade per cryptocurrency symbol**, regardless
of entry timeframe, direction, strategy, or signal source.

Risk blockers have three explicit scopes:

- **Trade-level** blockers evaluate only the proposed setup: direction, signal,
  confidence, timeframe conflict, freshness, and net reward/risk.
- **Coin-level** blockers apply only to the normalized symbol. An active BTCUSDT
  trade blocks every additional BTCUSDT timeframe or direction, but it must not
  block an otherwise eligible ETHUSDT, XRPUSDT, or other configured symbol.
- **Account-level** blockers apply across all symbols only for account controls,
  including the global open-trade cap, emergency/automation locks, and a genuine
  combined daily account loss-limit breach.

The daily-loss calculation must use each trade's own symbol price and convert
its underlying price return into account return using its governed risk size and
stop distance. Raw per-trade percentages must not be added together, and the
selected dashboard symbol's price must never value another coin's position.

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

The governed setup/trigger path uses one shared execution window for every
canonical timeframe: minimum confidence `40`, full-size boundary `60`, maximum
`100`. It evaluates each canonical timeframe as an independent candidate, does
not use aggregate stack confidence to rescue a candidate below `40`, and does
not require all four directions to align. The complete four-timeframe scan must
be available; among candidates passing the direction, confidence, order-flow,
freshness, timing, trade-plan, and risk guards, the strongest candidate's own
timeframe, candle, score, confidence, and regime are carried into the paper-trade
plan and risk decision.

Operational readiness is separate from code compliance. Every deployed database
must contain fresh, finalized candle coverage for all four canonical timeframes.
Missing timeframe data must produce an incomplete/neutral decision and must never
be silently replaced by another timeframe or mixed into that timeframe's regime.
An unchanged valid thesis must still refresh its risk decision at least once
before the 15-minute execution freshness boundary. Duplicate suppression may
reduce repeated writes, but it must expire early enough to re-evaluate current
price, ATR, stop, targets, net reward/risk, and position sizing.

For reporting, the four canonical timeframe directions are equally weighted:
each timeframe contributes 25 percentage points. Bullish, Bearish, Neutral, and
Unknown percentages are calculated as `direction count / 4 * 100`. This aggregate
percentage does not change any timeframe's regime or confidence. Regime confidence
is calculated independently by the selected rule for that single timeframe.

## QP-TI-002: Independent market-participation confirmation

**Status:** Implemented for new paper-trade entries. Live execution remains
disabled.

The market-participation trend is a separate `BULLISH`, `BEARISH`, or `NEUTRAL`
decision and must never replace or mutate an individual timeframe's regime. It
uses finalized Binance Spot evidence on `1h`, `2h`, `4h`, and `1d`, including
actual taker-buy and taker-sell quote volume, spot CVD, relative spot volume,
price/EMA structure, and dynamically calculated support and resistance zones.

Dynamic resistance or support must not be hard-coded to a published price. A
repeated-rejection adjustment requires at least two historical tests in the
calculated zone. A breakout requires acceptance above resistance; a breakdown
requires acceptance below support. A wick through a zone without confirming
closes is not acceptance.

The combined participation result may also use fresh futures open interest and
funding, observed (not estimated) liquidation pressure, ETH/BTC participation,
and configured-symbol breadth. ETF flows, macroeconomic conditions, regulatory
events, and corporate treasury flows may affect the score only when supplied by
a verified provider with timestamped evidence. Missing external-context data is
reported as unavailable and contributes zero; it must never be fabricated.

New paper-trade entry requires both governed decisions to agree:

- existing selected timeframe `BULLISH` + participation `BULLISH` permits a Long
  candidate to continue through risk checks;
- existing selected timeframe `BEARISH` + participation `BEARISH` permits a Short
  candidate to continue through risk checks;
- participation `NEUTRAL`, opposite, stale, degraded, or below absolute score
  `40` blocks the new entry;
- this confirmation must not delay or block monitoring and closure of an already
  active paper trade.

The participation result is a trade-level blocker. It does not change the
one-active-trade-per-symbol lock, account-wide limits, staged exits, or the
canonical rescan lifecycle in QP-TI-001.

The signal watchlist, market scanner, queued-plan persistence, and paper executor
must use the same participation guard and the same selected opportunity. When a
watchlist candidate is selected from `1h`, `2h`, `4h`, or `1d`, the dashboard must
show that candidate's timeframe, direction, score, confidence, participation
state, and combined eligibility together. A signal from the currently viewed
timeframe must not be labelled with another timeframe's eligibility.

# INR-M paper-wallet sizing

- Paper trading uses a governed starting wallet of **INR 200,000**. This is
  simulation capital only and never authorizes a live exchange order.
- Confidence from **40 to below 60** uses **75% position notional**:
  **INR 150,000 notional**, or **INR 30,000 initial margin at 5x**.
- Confidence of **60 or above** uses **85% position notional**:
  **INR 170,000 notional**, or **INR 34,000 initial margin at 5x**.
- The account-wide paper margin ceiling is **85% of the INR 200,000 wallet**.
  Margin already committed to every open coin is included before a new entry.
- Max-risk, daily-loss, and account open-trade count are monitoring fields and
  do not block paper entries. One active trade per coin remains mandatory, and
  wallet margin availability must still be sufficient for every new entry.
- Contract prices may remain USDT-quoted market references, but INR capital is
  never divided directly by a USDT price. INR notional, margin and P&L remain
  separate from quote-price data until an exchange conversion rate is present.
