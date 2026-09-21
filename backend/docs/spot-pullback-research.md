# Confidential: isolated spot-pullback research

This implements the first historical-screen stage of the 2026-09-21 proposal.
It is not a replacement for the governed `TREND_PULLBACK` strategy. The research
identifier is `SPOT_TREND_PULLBACK_RESEARCH_V1` and has no registry, database,
API, scheduler, official paper-wallet, learning-job or exchange-order integration.
User authorization is the request to proceed with the isolated research candidate.

## Governance boundary

The existing 1h/2h/4h/1d selection, INR wallet, leverage and staged exits remain
authoritative for the existing application. This standalone numerical experiment
uses 1h context/15m entries, an unleveraged quote-currency cash wallet, 0.25% risk,
maximum two positions and 1.5R full exits. Its distinct experimental policy does
not grant permission to use those different rules in official paper/live lanes.
Promotion is hard-disabled even if all descriptive metric gates pass.

## Run from backend

```powershell
.\venv\Scripts\python.exe scripts/run_spot_pullback_research.py fetch --directory outputs/spot_pullback_research/data --first-month 2023-01 --last-month 2025-12
.\venv\Scripts\python.exe scripts/run_spot_pullback_research.py run --directory outputs/spot_pullback_research/data --history-start 2023-04-01T00:00:00Z --start 2024-01-01T00:00:00Z --end 2026-01-01T00:00:00Z --output outputs/spot_pullback_research/screen_001
.\venv\Scripts\python.exe -m pytest tests/test_spot_pullback_research.py -q
```

Downloads use public Binance spot archives with official SHA256 checksums; no
credentials or strategy payload are sent. Archives are retained. CSV hashes,
engine hash, configuration hash, timestamps, fills, daily returns and stop reviews
are saved in each new output directory. Existing experiment directories cannot be
overwritten by the CLI. These are local reproducibility controls, not tamper-proof
storage. The data directory is inside the user's existing OneDrive workspace.

CSV columns: `timestamp,open,high,low,close,quote_volume`. Timestamps are UTC bar
open times. Inputs must be continuous, unique, ordered, valid 15-minute bars.
Evaluation is start-inclusive/end-exclusive. Earlier rows are indicator warm-up.
At least 90 days plus indicator seeding history are required for volatility
eligibility; the example provides nine preceding months. The downloaded March
2023 archives have five missing bars per symbol, so this explicit warm-up cut
uses continuous data from April 2023. Evaluation dates were not changed in
response to performance. Gaps fail the run rather
than manufacturing candles or valuing open positions with stale prices.

## What is implemented

- SMA-seeded EMA20/50/200, Wilder ATR14, completed-hour trend context, trailing
  90-day volatility threshold, completed-day turnover and completed-bar volume.
- Frozen recovery signal, BTC confirmation for ETH, next-open simulated fills,
  entry price cap, stop-distance and fee-to-risk rejection rules.
- Shared cash/exposure/risk accounting, one position per coin, at most three
  entries per UTC day, one-hour post-stop cooldown, 1% daily/3% weekly/5% drawdown
  circuit breakers. Weekly/drawdown halts remain latched through the experiment.
- Stop-first ambiguous bars, adverse gap fills, fees and execution costs, trend
  exits, six-hour expiry, explicit end-of-sample liquidation.
- Conservative intrabar low marks plus closing marked equity. Synchronized
  portfolio low marks overstate simultaneity; they are not tick reconstruction.
- Baseline, doubled execution costs and one-bar delayed entry sensitivity runs.
  Each reruns admission gates, so trade populations can differ.
- Deterministic stop reviews preserve uncertainty. Actual gaps are observed;
  news, market manipulation and stop-placement causation are not invented.

## What these results cannot prove

The screen deliberately omits unverifiable historical quote/depth conditions,
five-second order cancellation, partial fills, tick/lot sizes, news/calendar vetoes,
listing-age and reconstructed top-20 universe membership. Fixed BTC/ETH is a
development sample, not evidence for all coins. No options/OI filters are added.
USD-like quote-unit turnover assumes USDT parity; no INR/USDT conversion or taxes
are modeled. Daily-loss halts use 15-minute evidence and can overshoot a threshold.

Data from 2026 is not downloaded by the example; however, no past period is
claimed to be untouched because its prior use elsewhere is unknown. The run is
an exploratory screen without parameter tuning. Cost/latency scenarios are not
walk-forward folds or independent observations. The descriptive Wilson bound
assumes independent trials and cannot establish an 80% win-rate claim.

Still required before promotion: a point-in-time eligible universe, historical
execution/event evidence, chronological walk-forward and reserved-coin tests,
selection/dependence-aware uncertainty, benchmark/ablation and parameter-stability
analysis, genuinely untouched or prospective evidence, and >=90 days AND >=100
completed forward paper trades. No automatic learning changes are applied.

## Fixed horizon/cap comparison — 2026-09-21

The user requested the next research step and confirmed continued use of Binance
data. `spot-pullback-comparison-plan.json` records five policy definitions before
their results: four pullback combinations plus one simpler trend-transition
comparator. Two additional cost/latency scenarios are assigned to the hourly,
0.5 ATR cap variant in advance, regardless of its outcome. No policy winner is
automatically selected or promoted.

```powershell
.\venv\Scripts\python.exe scripts/compare_spot_pullback.py --directory outputs/spot_pullback_research/data --output outputs/spot_pullback_research/comparison_001
.\venv\Scripts\python.exe -m pytest tests/test_spot_pullback_research.py tests/test_spot_pullback_comparison.py -q
```

Each run uses a new version identifier under `SPOT_COMPARISON_V1_`. The original
default signal rules remain unchanged and have a feature-equivalence regression
test. Hourly variants use hourly indicators/volume confirmation, four-hour trend
context and a 24-hour hold; the stop/cash/exposure/loss limits stay unchanged.
Execution and the liquidity-cap reference remain at 15-minute resolution.
Hourly entry signals occur only once at availability time; context exits remain
available between signal bars. The wider cap remains 0.5 ATR, not unrestricted
market chasing. The trend comparator enters on a new bullish context state and
uses a two-ATR stop with the same risk and cost gates.

The current published regular-user Binance spot rate was verified as 0.10% per
side at https://www.binance.com/en/fee/trading on 2026-09-21. This supports the
fee scenario but does not reconstruct historical promotions or confirm the user's
account tier. The 5 bps per-side spread/slippage allowance remains unmeasured.
Actual fees can be charged in received assets or BNB; the simulator charges their
quote-currency equivalent and does not model fee-asset balances or lot rounding.

`registration.json` captures the local plan, dataset and code hashes before trial
execution. The runner refuses to overwrite a run and checks code/plan consistency
afterward. This is local provenance, not an externally certified preregistration.
Each policy gets its own independent research wallet, but its BTC/ETH positions
share capital. All seven outcomes are retained, together with daily returns,
stop reviews and compressed marked-equity curves. Calendar-year decomposition
does not reset the wallet or its circuit breakers. Weekly-block intervals describe
daily returns and are neither selection-adjusted nor a substitute for trade
expectancy validation. Cash and initial 50%/100% BTC/ETH buy-and-hold portfolios
are reference benchmarks with explicitly different risk/exposure.

This remains a comparison on previously inspected development data. No 2026
prices or other assets are loaded. All original execution, universe and promotion
limitations still apply.

## Frozen trend transfer validation — 2026-09-21

The next authorized stage tests the existing `B1_TREND_ONLY` policy unchanged.
`spot-trend-validation-plan.json` fixes January–August 2026 and a separate
SOL/XRP/BNB cohort before acquiring their prices. Each of the two cohorts runs
baseline, doubled execution cost and 15-minute latency scenarios. BTC/ETH form
the first cohort; BTC is a context-only input in the second. Cohort capital is
independent; stress runs are overlapping evidence, never pooled sample counts.

```powershell
.\venv\Scripts\python.exe scripts/validate_spot_trend.py register --output outputs/spot_pullback_research/validation_001 --reference outputs/spot_pullback_research/comparison_001
.\venv\Scripts\python.exe scripts/validate_spot_trend.py fetch --output outputs/spot_pullback_research/validation_001
.\venv\Scripts\python.exe scripts/validate_spot_trend.py run --output outputs/spot_pullback_research/validation_001
```

Registration verifies that both the policy definition and the signal-feature
module hash match the prior comparison, then records plan/code hashes BEFORE
data acquisition. Fetching verifies publisher archive checksums; executing records
CSV hashes, preserves every result and checks for input/code changes afterward.
The runner does not overwrite existing registration or started runs. A data gap
fails visibly without filling it or replacing the coin. The rule implementation
is frozen; the engine adds only a tested tradable-symbol whitelist to prevent
BTC context from entering the additional-coin wallet.

The additional coins are an explicitly purposive surviving-asset sample, not a
point-in-time universe. 2026 is new within this research sequence; previous use
elsewhere is unknown. This is a temporal/asset transfer test, not a prospective
paper record. Once accessed, these prices cannot be called unseen in future
tuning. Numeric failures and absent forward/execution evidence continue to block
all promotion, even if one coin or scenario appears profitable.
