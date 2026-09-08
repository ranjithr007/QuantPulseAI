# Market Move controlled paper experiments (original v1 reference)

Current rollout: see [Structure-entry and delayed-trailing experiments](structure_entry_delayed_trailing.md).
The entry experiments below describe the historical v1 cohort. New Market Move
and Regime Trend entry decisions use v2; existing history is not rewritten.

These strategies run in isolated Strategy Paper books. They do not enter the
consolidated book or enable live execution. The incumbent `MARKET_MOVE` and its
40-point eligibility threshold are unchanged. Existing Regime Trend Entry
Candidate remains the entry-only control for that strategy; it is not duplicated.

| Strategy / version | Entry | Exit management |
| --- | --- | --- |
| `MARKET_MOVE` / `market_move_v1` | Existing participation decision | Existing adaptive policy |
| `MARKET_MOVE_ENTRY` / `market_move_entry_v1` | Same decision plus confirmed retest and final-fill location gate | Same initial adaptive exits and immediate trailing |
| `MARKET_MOVE_EXIT` / `market_move_exit_v1` | Same incumbent decision | Same initial adaptive exits; continuous trailing activates at +1R |

The entry experiment requires at least two boundary tests and latest rejection,
directional spot CVD, price on the correct side of EMA within one ATR, and a
tested support/resistance boundary within one ATR. The execution price and the
simulated fill must remain within 0.5 ATR of the planned retest entry. The
location snapshot must be at most 15 minutes old and the execution mark at most
60 seconds old, with five seconds of allowed clock skew. Missing, non-finite,
stale or side-inconsistent evidence fails closed. All distances use the selected
timeframe's recorded ATR. Repricing uses that ATR and structural boundary;
an execution-time price refresh alone is not a fresh retest.

These fixed constants belong to version 1 of the experiment; future changes
require another strategy version. Automatic learning cannot rewrite or promote
these frozen experiments into consolidated execution. A database promotion flag
alone does not override their isolated-book restriction.

## Evaluation and attribution

New trades record the exit policy and execution evidence containing entry-quality
profile, exit-management profile, sizing policy and release version. Learning
selects the most recently observed fully attributed cohort and analyzes up to
its latest 30 closed trades. Cohorts are never padded with old fixed-policy or
different-sizing trades. Unknown historical metadata remains visible as
`LEGACY_DIAGNOSTIC_ONLY`; it cannot create or promote learned candidates.

The `pre_t1_losing_stops` diagnostic preserves the former count of any negative
stop exit before T1. `initial_stop_failures` now specifically counts negative
exits whose recorded stop was still the original stop. Trailed pre-T1,
protected after-T1 and unknown stops are separate. Historical level comparisons
are labelled inference, not newly observed trigger evidence.

Thirty trades are an initial diagnostic milestone, not evidence that a strategy
will maintain a 55% win rate. Compare both directions and strategy books
separately, after fees, funding and slippage. Review entry-location failures,
sampled adverse/favorable excursions and data coverage before changing a
parameter. Keep the incumbent and each experiment separate; do not optimize
entry and exit rules together and attribute the result to one improvement.
