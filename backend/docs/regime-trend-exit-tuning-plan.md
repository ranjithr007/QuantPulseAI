# Regime Trend exit tuning plan

Status: research-only; no operational parameter change is authorized by this
document.

## Problem statement

The current `REGIME_TREND@regime_trend_v1` paper evidence contains many
pre-Target-1 trailing stops and a low win rate. The first experiment therefore
holds entry generation constant and tests exit management separately.

## Frozen candidates

| Candidate | Exit change | Exposure |
| --- | --- | --- |
| `BASELINE` | Current exit policy, recorded for comparison | 1x |
| `TRAIL_075R` | Do not advance the protective trail until price reaches 0.75R | 1x |
| `TRAIL_100R` | Do not advance the protective trail until price reaches 1.00R | 1x |
| `STRUCTURE_STOP` | Use the confirmed structure boundary plus an ATR buffer, with a hard maximum loss cap | 1x |

The entry signal, timeframe selection, regime routing, symbol universe, data
cutoff, and position-risk fraction remain unchanged. The variants are fixed
before evaluating the outcome period; no per-symbol or per-regime retuning is
allowed.

## Validation

- Use chronological walk-forward windows with a separate untouched evaluation
  period.
- Include fees, conservative entry/exit slippage, and missing-data handling.
- Require at least 30 mature trades for each candidate before ranking it.
- Report win rate, profit factor, expectancy, maximum drawdown, stop-out rate,
  Target-1 rate, Target-2 rate, and results by symbol and regime.
- A candidate must improve profit factor and drawdown out of sample while
  remaining positive after costs. A higher win rate alone is insufficient.
- The existing version remains frozen and available for comparison.

## Hardening controls for any successor

Every successor must fail closed when any of these conditions is missing:

- finalized candles and regime/feature inputs are fresh and timestamp-aligned;
- at least two governed timeframes agree on direction and the selected regime
  is one of `TRENDING_BULL`, `BULL_PULLBACK`, `TRENDING_BEAR`, or `BEAR_RALLY`;
- a confirmed structure event and ATR-based stop are present at execution;
- simulated exposure is spot-like 1x with a fixed per-trade risk cap, daily loss
  cap, weekly loss cap, and one-position-per-symbol limit;
- fees, slippage, spread, and missing-feed behavior are represented in the
  result; and
- a monitoring gap, stale quote, or data contradiction blocks new entries and
  records the reason.

No adaptive threshold, loss-triggered retuning, symbol-specific exception, or
confidence-based size increase may be introduced during the evaluation window.

## Promotion boundary

This plan cannot enable a new strategy version, alter the official paper wallet,
or authorize live execution. A passing result requires a separately versioned
strategy definition, recorded evidence, and an explicit governance decision.

## Entry replay result

The 30-day Binance replay (28 August through 22 September 2026) paired 624 mature
trades. The recorded current exit produced a 27.7% win rate, 0.37 profit factor,
and -0.386% average return after costs. The signal was already negative before
execution costs (-0.079% average gross signal return), and 58.5% of resolved
trades reached 0.25R adverse excursion before favourable excursion. Entry slippage
contributes to the loss but is not the primary cause. No entry or exit candidate
is promoted from this sample; a future entry study should test delayed
confirmation and a strict entry-slippage cap on a fresh chronological holdout.

## Next research candidate (not enabled)

Define an immutable `regime_trend_entry_confirmed_v1` research candidate with
the existing signal, regime, symbol, and risk inputs unchanged. It may enter
only after the next finalized candle confirms the same direction and the
estimated entry slippage is at or below 0.05%. The candidate must be compared
with the unchanged control on a chronological holdout; the slippage cap is an
execution guard, not a signal-quality claim. It cannot be enabled from the
current replay because the low-slippage cohort remained negative.
