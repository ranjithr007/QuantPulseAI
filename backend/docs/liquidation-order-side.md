# Liquidation scoring contract

Binance force-order `S` is the closing order side: SELL liquidates a LONG;
BUY liquidates a SHORT. Never infer the liquidated position from whether an
event price is above or below today's price.

`ORDER_SIDE_V1` aggregates valid Binance observations within the last four hours,
bounded by the evaluation's as-of timestamp. The score is
`100 * (short USD - long USD) / (short USD + long USD)`.
The participation component uses this same score scaled to its existing ±8 budget.
Positive is observed forced-buy pressure, negative observed forced-sell pressure;
neither is a continuation prediction or a calibrated confidence probability.

If no valid observations exist or the latest valid event is over 30 minutes old,
the directional score is unavailable. Retained stale totals are informational.
Historical price clusters remain descriptive and do not generate hunt labels or
future price targets. Raw side values and historical trade results are not rewritten.

Totals cover collected Binance snapshots, not complete market-wide liquidation
volume. The exchange stream can omit events within its snapshot interval.

Deploy the API, worker and frontend together. No new DB schema is required:
the participation JSON persists side totals, score, methodology and window metadata.
Old HUNT heatmap labels no longer create directional votes. Cached participation
with a nonzero legacy liquidation component cannot authorize entries until the
normal pipeline produces a corrected snapshot; liquidation-carry requires the
new methodology. Normal automatic scans refresh the current evidence.
