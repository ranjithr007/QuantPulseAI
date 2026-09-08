# Structure-entry and delayed-trailing paper experiments

These experiments use isolated Strategy Paper books. They cannot enter the
consolidated book or enable live exchange execution. The incumbent Core Signal,
Regime Trend and Market Move strategies, their scores and 40-point threshold
are unchanged. Entry and exit changes are deliberately tested separately.

| Strategy / version | Entry | Exit management |
| --- | --- | --- |
| `CORE_SIGNAL_ENTRY` / `core_signal_entry_v1` | Core Signal plus confirmed price structure | Original exits and immediate trailing |
| `CORE_SIGNAL_EXIT` / `core_signal_exit_v1` | Original Core Signal | Original hard stop/targets; continuous trailing activates at +1R |
| `REGIME_TREND_ENTRY` / `regime_trend_entry_v2` | Aligned Feature/Regime plus confirmed price structure | Original exits and immediate trailing |
| `REGIME_TREND_EXIT` / `regime_trend_exit_v1` | Original Regime Trend | Original hard stop/targets; continuous trailing activates at +1R |
| `MARKET_MOVE_ENTRY` / `market_move_entry_v2` | Original Market Move plus confirmed price structure | Original adaptive exits and immediate trailing |
| `MARKET_MOVE_EXIT` / `market_move_exit_v1` | Original Market Move | Original adaptive exits; continuous trailing activates at +1R |

## Entry gap: directional score is not entry confirmation

Each of 1h, 2h, 4h and 1d is evaluated independently before ranking eligible
timeframes. Failed structure confirmation removes that timeframe from the entry
candidate; another confirmed timeframe can still qualify. The incumbent's
eligibility checks still apply. A WAIT incumbent is never rescued by this gate.

The frozen `CONFIRMED_PRICE_STRUCTURE_V1` profile requires either:

- A closed breakout through a previously confirmed swing, followed by a later
  closed retest that holds on the correct side.
- An intact higher-high/higher-low trend and a recovered pullback for Long, or
  mirrored lower-high/lower-low structure for Short.

Higher lows alone do not confirm a Long entry. Compression needs a confirmed
breakout, not just a positive score. The evidence uses at least 25 explicit final,
contiguous candles from the same coin/timeframe. Pivots require two bars on each
side and are usable only after confirmation. Event tests use ATR available before
the event, preventing future candles from changing a past event threshold.

Frozen constants: ATR 14; breakout buffer 0.05 ATR; retest/invalidation tolerance
0.25 ATR; confirmation within the latest three closed bars; retest/recovery at
most five bars after its event; compression is a ten-bar span at most 1.5 ATR.
Missing, malformed, future-dated or conflicting structure fails closed.

Entry also requires directional spot CVD and execution price on the correct side
of EMA and the confirmed level, within one ATR. Both the fresh execution mark and
the simulated fill are checked: maximum drift from the planned entry is 0.5 ATR.
The scan must be at most 15 minutes old; mark at most 60 seconds old (five seconds
clock skew allowed). The source candle must match the spot source timestamp and
be no older than one selected-timeframe duration plus 15 minutes. A refreshed scan
timestamp does not make old candles fresh. The collector records `collected_at`
separately from the candle-based `effective_timestamp`; cache reads do not renew
either timestamp. These are admission freshness bounds,
not a promise of tick-level latency.

Structure levels are recorded as diagnostics, not executor exit overrides. The
entry-only experiment does not widen the original stop or substitute new targets.

## Exit gap: continuous trailing before T1

Exit-only candidates keep their baseline entries and initial hard stop, T1, T2,
partial-close fraction and maximum holding time. Continuous trailing waits for a
favorable move equal to the **initial entry-to-stop distance** (+1R). Once active,
the stop can tighten but never loosen. Long and Short use mirrored rules.

The initial stop remains enforced before activation, including equality and gaps.
T1 partial exits/profit protection, the later T1-level protection, T2 and holding
deadline remain enforced independently of continuous-trailing activation. A gap,
slippage or costs can still make realized loss exceed the planned stop distance.
Delaying trailing can reduce early noise exits but can also give back more profit;
it is a hypothesis to measure, not a guaranteed improvement.

## Isolation, rollout and audit

All six candidates are immutable paper experiments. Automatic learning cannot
rewrite or promote them into consolidated execution. Each family has one active
trade per coin across its canonical experiment revisions and timeframes. A still
open v1 entry trade blocks same-coin v2 admission until closed; same-direction
stop cooldown also spans those revisions. Other candidate books remain independent.
Performance, capital accounting and learning cohorts remain version-specific.
Existing v1 entry cohorts remain visible as read-only history in Strategies;
they are not offered for new admission or mixed into the v2 statistics.

No schema migration or historical rewrite is required. New structure evidence is
saved in existing decision/execution JSON; delayed activation uses the existing
column. Existing open trades retain their recorded exit settings. After deploying
web/API and worker, wait for fresh collector/scanner output: cached pre-release
evidence must not qualify the new entry versions. Complete the worker rollout
before relying on cross-version admission locks; an old running binary does not
know the new shared-lock convention.

Trade audits expose setup type, timeframe, candle close in IST, confirmed level,
invalidation level, gate outcome and trailing activation. Historical missing
evidence remains unknown, not retroactively confirmed. A protected-stop summary
includes after-T1 stops and non-losing before-T1 stops; inspect the detailed exit
classification before attributing a loss to T1 protection.

Recorded-decision backtest comparison retains the saved trailing activation and
keeps revisions separate. It does not regenerate historical structure or repeat
the live mark/fill freshness gate. Five-minute OHLC cannot reproduce tick-level
execution; its declared limitations still apply. The replay-policy cache revision
prevents new requests from reusing comparisons made before the metadata fix.

## Evaluation and attribution

Compare each entry-only and exit-only candidate with its unchanged baseline after
at least 30 newly attributed closed paper trades per cohort. Do not pad the sample
with older strategy versions, exit policies or sizing regimes. Review initial-stop
failures, pre-T1 trailed losses, T1/T2 success, net expectancy, drawdown, excursions,
costs and data coverage, split by direction and timeframe where sample size allows.

Thirty trades are a diagnostic milestone, not proof of a 55% win rate or future
profitability. Do not combine entry and exit changes or promote a candidate until
independent prospective evidence supports doing so. All live execution remains
outside this release's authorization.
