# Confidential — range-reversion hypothesis V1

Status: a new, untested hypothesis, not an approved strategy. Defined on
2026-09-21 before any evaluation of these rules. No result from a future test
may be presented as established in this document.

## Economic hypothesis

In a sufficiently stable range, some moves below a recent volatility band may
reverse toward the recent average rather than start a sustained decline. A
confirmed recovery may provide a testable entry. This mechanism is a hypothesis,
not a finding that such reversals are predictable or profitable after costs.
It differs from the rejected trend-transition/pullback entries: the intended
profit source is a return toward the mean, not continuation of a directional
trend. Its principal failure mode is mistaking the start of a decline for a
temporary excursion. A high win rate can conceal rare large losses, so the
objective remains net expectancy and drawdown, not manufacturing 80% winners.

## Frozen initial rules

Use Binance spot, long only, no borrowing. Initial development symbols remain
BTCUSDT and ETHUSDT; no coin is removed after seeing results. All bars and daily
loss boundaries use UTC. Signal candles are completed 1h bars; regime candles
are the latest completed 4h bars. Execute/replay at 15m or finer resolution.

Indicators: hourly SMA20 and population standard deviation of the same 20 closes
(ddof=0), lower band = SMA20 - 2*standard deviation; Wilder ATR14 on 1h and 4h;
Wilder ADX14 on 4h. EMA50 uses alpha 2/51 and an initial 50-close SMA seed.
Wilder smoothing uses an initial arithmetic mean and then alpha 1/14.
For ADX, positive DM is the positive upward-high change only when it exceeds
downward-low change; negative DM is defined symmetrically; ties give both zero.
Smooth TR and the two DM series for DI, compute DX, then Wilder-smooth DX.
Exclude the first candle without a previous high/low/close. If smoothed TR is
zero, both DI values are zero; if their sum is zero, DX is zero. Require at least
250 completed 4h bars before decisions and never use partial higher-timeframe bars.

An entry requires every condition below at hourly signal close t:

1. The latest completed 4h ADX14 is below 20, and the absolute change in 4h
   EMA50 over the preceding six completed 4h intervals is <= one current 4h ATR14.
2. The preceding hourly bar t-1 closed below its own lower band.
3. Bar t closes above its own lower band and above its own open, but remains
   below its own SMA20. This requires observed recovery, not merely a falling price.
4. Bar t's true range is <=2 times ATR14 from t-1, excluding large shock bars.
5. The preceding 30 full days' median daily quote turnover is >=USDT 50 million.
   Missing history blocks entry. Historical liquidity/universe limitations must
   be explicit; turnover cannot substitute for executable order-book depth.

After bar t closes, consider only the next executable ask. The entry price cap
is close[t] + 0.25*ATR14[t]. Do not chase. In an OHLCV development screen, use the
next 15m open plus the predeclared execution allowance and reject fills above
the cap; clearly distinguish this approximation from verified limit execution.

Initial stop S = min(low[t-1], low[t]) - 0.25*ATR14[t]. For actual fill E, let
d = E-S. Require 1 <= d/ATR14[t] <= 3 and d/E <=3%; otherwise skip. Never widen
the stop, average down or rescue a losing entry. Fixed target T = SMA20[t],
captured at the signal time; do not move it retrospectively with later bars.

Use the existing conservative fee/execution scenario: fee f=0.001 per side and
execution allowance s=0.0005 per side, with E already including entry execution.
For admission, use an additional conservative per-unit reserve c=2E(f+s).
Require c/d <=0.15, T>E, and `(T-E-c)/(d+c) >=1.5`. The latter is a conservative
net reward/risk filter, not a claim of realized payoffs. Size against d+c.
Do not lower the cost reserve to make more trades pass after seeing results.

Exit at the earliest of: protective stop, fixed mean target, 24-hour hold deadline,
or the first completed 4h ADX14 >=25. The latter triggers an exit at the next
executable price, not retroactively at the regime candle close. Gap stops fill
at the adverse available price; use stop-first ordering for ambiguous OHLC bars.
No staged targets, discretionary stop moves, grid positions or martingale.

## Risk and execution rules

Retain research risk 0.25% of marked equity per trade, <=0.50% combined original
stop risk, <=25% equity notional per position, <=50% total gross exposure, two
positions and three new entries per UTC day. One position per symbol; after a
stop, one-hour cooldown plus a fresh qualifying hourly signal. Stop trading at
the existing 1% daily/3% weekly/5% high-water drawdown limits. Gaps can exceed
these intended limits. All crypto positions share one correlated risk allowance.

Quantity is the minimum of risk budget/(d+c), per-position notional capacity,
cash including entry fee, remaining portfolio capacity and 0.1% of the preceding
15m quote volume. Round down using verified venue filters before any executable
paper simulation. Never treat fractional unrounded historical estimates as
exchange-valid orders. At equal opportunity times rank by prior 30-day median
quote turnover, then symbol name. Missing data or unknown position state blocks entry.

Actual or realistic forward execution additionally requires observed spread <=10
bps, sufficient displayed depth, current instrument status and lot/notional
filters, and a healthy feed. News/incident vetoes require point-in-time evidence.
Without those inputs, label a historical screen incomplete; do not invent them.

## Test plan and anti-overfitting restrictions

This is ONE fixed candidate. First assess implementation and economic feasibility
on the already-consumed BTC/ETH 2024–2025 development data, with chronological
yearly results, no year-end risk-wallet resets and April–December 2023 warm-up.
Use cash and exposure-disclosed buy-and-hold benchmarks; retain the rejected
trend candidate as an already-existing comparator. Preregister baseline, doubled
execution-cost and 15-minute-delay scenarios; run all three regardless of outcome.
No grid search, alternate RSI thresholds, volume additions or winner coin selection.

The 2026 January–August and SOL/XRP/BNB prices were already consumed by another
strategy's validation. They can support labeled exploratory analysis, but must
not be rebranded untouched for this new hypothesis. Do not load another price
period under this specification without recording its role first.

If the development screen has insufficient trades, nonpositive after-cost
expectancy or poor cost robustness, reject it rather than relaxing gates until
it trades. Existing promotion requirements remain: adequate samples, positive
expectancy with dependence/selection-aware evidence, PF>=1.25, acceptable marked
drawdown, cross-asset evidence, realistic execution and at least 90 days AND 100
completed prospective paper trades. These are necessary, not sufficient, gates.

After a loss, retain price/feature/fill evidence and allow ordinary-loss/unknown
classifications. A later recovery does not prove the stop was wrong. Statistical
changes require recurring evidence across winners and losers, a new version,
new registered tests and genuinely new validation; never alter a live position
or deploy a patch automatically.

## What has and has not been done

The public order-book probe is a separate, bounded, read-only feasibility check.
It does not test this signal, prove fills, reconstruct historical spreads or
justify lower historical slippage assumptions. No background collection or
automation is enabled. This hypothesis is documented but not implemented,
backtested, registered in the application or approved for paper/live execution.
Its next concrete deliverable would be a single reproducible development screen,
including a failure result, under the frozen rules above.
