# Confidential — range-reversion development implementation

This implements the previously documented rules in
`spot-range-reversion-hypothesis-v1.md`. That document is retained unchanged as
the specification that existed before implementation and results. The strategy
ID is `SPOT_RANGE_REVERSION_HYPOTHESIS_V1`; it is an offline numerical experiment,
not the existing operational `RANGE_REVERSION` strategy.

```powershell
.\venv\Scripts\python.exe scripts/screen_spot_range.py --directory outputs/spot_pullback_research/data --output outputs/spot_range_reversion/screen_001 --previous-comparison outputs/spot_pullback_research/comparison_001
.\venv\Scripts\python.exe -m pytest tests/test_spot_pullback_research.py tests/test_spot_pullback_comparison.py tests/test_spot_trend_validation.py tests/test_spot_range_reversion.py -q
```

The runner records specification/code hashes and all three configurations before
any trial, uses only already-consumed BTC/ETH development data, preserves every
outcome and checks hashes afterward. New output directories are required. No
price-download function is called. Prior 2026 validation prices are not loaded.

Indicators exclude the initial candle without prior high/low/close for Wilder
TR/DM initialization, per specification. ATR's initial seed follows 14 valid
true ranges; ADX follows 14 valid DX observations. Zero denominators produce
zero DI/DX after warm-up, not nonfinite values. Population band deviation uses
ddof=0. Four-hour regime observations become available only at their close;
hourly entry signals are emitted once and are never forward-filled as new entries.

The shared research portfolio engine now accepts an explicitly identified range
policy. Its plan uses the fixed signal-time SMA target, up to three ATR stop
distance, a 0.25 ATR entry cap, conservative net reward/risk >=1.5, 24-hour hold
and ADX-based `RANGE_BREAK` exit. Original trend default behavior remains covered
by regression tests. Range sizing includes remaining gross-notional capacity.
All account risk, stop-first, cash, cooldown and circuit-breaker controls remain.

Baseline fees remain 10 bps and adverse execution 5 bps per side. The adverse
cost scenario doubles execution cost; the latency scenario delays entry 15
minutes. Each reruns admission checks and can produce a different trade set.
The short live order-book probe does not replace these historical assumptions.

First-failure counts explain rejected candidate entries. They are conditional
counts and cannot establish independent causal effects of removing filters.
Annual decompositions retain one continuous wallet and all risk latches. The
previous trend baseline is imported as existing evidence; cash and initial
50%/100% buy-and-hold allocations remain explicitly risk-unmatched benchmarks.

Missing venue lot filters, historical quotes/depth, news and real fill evidence
remain material limitations. Unrounded simulated quantities are not executable
orders. No automatic learning, API route, registry entry, scheduler, operational
paper wallet or live trading setting is changed. This experiment cannot authorize
promotion or substantiate an 80% win rate.
