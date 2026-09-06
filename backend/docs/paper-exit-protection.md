# One-second paper exit protection

`paper_trade_fast_exit` runs independently every second, on its own scheduler
executor (`paper_exits`, one concurrent instance, coalesced missed runs). Workers
configured with the deterministic pipeline, pipeline cycle, paper monitor, or
paper executor automatically include it. Collector-only workers remain unchanged.

The worker subscribes once to Binance futures' market-routed
`!markPrice@arr@1s` WebSocket. All open coins and both paper books share that feed;
there is no REST request per position or database insertion per received tick.
HOLD decisions use a per-run snapshot. Mutations re-read the position under a
database row lock; the candle reconciler uses the same locking protocol.

The fast path checks stops, T1, T2, trailing protection and maximum holding time.
T1 and T2 can execute on the same received mark. Tick-driven trailing updates do
not create a notification every second. T1 cannot loosen an existing tighter stop.
When protection changes on a live tick, its timestamp is retained in the exit
checkpoint so historical candles do not retroactively trigger the new stop.

Quotes older than five seconds, invalid prices, out-of-order frames, and quotes
predating entry are rejected. A stale/missing feed or checks taking over two
seconds generate a rate-limited critical in-app notification. Database-wide failures
also surface in scheduler logs. The slow candle monitor remains for recovery.
The one-second interval is a target, not a guaranteed latency SLA: network delays,
database contention, worker downtime and price gaps can still worsen fills.
P&L remains based on the simulated fill and actual configured costs; it is never
clipped to the stop percentage.

## Release verification

1. Deploy the API and worker from the same commit. No schema migration is added.
2. Confirm the worker schedules `paper_trade_fast_exit` with a one-second interval.
3. From the worker container run the read-only probe:
   `python scripts/check_paper_exit_stream.py`.
   This verifies public feed receipt only; it does not test DB writes or place trades.
4. Check worker logs for execution skips, connection/DB failures, and notification
   alerts. Confirm real paper exit events on the next naturally occurring trigger;
   do not fabricate positions in the production book for verification.

No live exchange orders are authorized or implemented by this feature.

## Recovery limitations and safeguards

Row locks fail immediately if another monitor owns the position. The next run
retries, and quote age is checked again after the lock is acquired.
Completed candles advance the checkpoint to their close, not their open.
An overlapping candle cannot reveal whether a wick occurred before or after a
stop change. Its known closing price is evaluated and the job reports
`INTRABAR_RECOVERY_AMBIGUOUS_CLOSE_ONLY`; intrabar fills are not fabricated.
For an unambiguous candle reaching both targets without touching the old stop,
both legs close in the same reconciliation pass. Candle-based exits use the
candle close as the evidence-time bound for funding, rather than processing time.
This is not a claim of exact intrabar execution timing.

Saved learning reports without `NET_STOP_V2` are retained and labelled legacy.
They cannot be used as promotion benchmarks. The next scheduled milestone
generates corrected metrics; old historical reports are not rewritten.
