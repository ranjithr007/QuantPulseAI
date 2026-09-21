# Isolated range-reversion forward paper experiment

User-authorized on 2026-09-21 after the candidate's failed development screen.
This is permission to collect exploratory forward paper evidence, NOT validation
or promotion to the official wallet or real-money execution.

- Version: `SPOT_RANGE_FORWARD_PAPER_V1`.
- Wallet: 10,000 virtual USDT; BTCUSDT and ETHUSDT only, no borrowing/leverage.
- Per-trade risk: 0.10% marked equity (initially 10 USDT), including cost reserve.
- Existing 0.50% aggregate planned risk, 25% per-position notional, 50% gross
  exposure, two positions, three entries/day, 1% daily/3% weekly/5% drawdown
  controls remain. Actual two-position risk is normally <=0.20% at this sizing.
- Frozen range signal, fixed SMA target, structural stop, 24h time exit, ADX
  range-break exit, cooldown and cost/reward gates remain. No automatic learning.

The worker is standalone and uses only allowlisted public market-data GETs on
Binance's market-data-only domain. There is no account credential support or
order/test-order endpoint. It does not load application settings or operational
database credentials, register an API strategy, or alter the existing scheduler.

## Commands (from backend)

```powershell
.\venv\Scripts\python.exe scripts/run_range_paper.py run --directory outputs/range_forward_paper/session_001
.\venv\Scripts\python.exe scripts/run_range_paper.py status --directory outputs/range_forward_paper/session_001
.\venv\Scripts\python.exe scripts/run_range_paper.py pause --directory outputs/range_forward_paper/session_001
.\venv\Scripts\python.exe scripts/run_range_paper.py stop --directory outputs/range_forward_paper/session_001
```

`pause` blocks new entries while the worker continues exits. `stop` requests
worker shutdown and leaves any open simulations for explicit reconciliation;
use pause if you want protective monitoring to continue. No automatic resume or
state reset is provided. Restart gaps >60 seconds latch new entries off; existing
positions still receive available protective/time exits. A code hash mismatch
refuses startup rather than silently applying changed rules to the old wallet.

The worker runs locally while this computer remains awake and connected. It is
not a cloud service and is not configured to restart at Windows login. Polling
is approximately 15 seconds; candle features refresh on 15m boundaries and only
new completed hourly signals may enter. Sixty-five days of initial candle
warm-up are fetched and persisted; later runs append finalized candles without
moving the original indicator seed. Startup history never backfills trades.
Signals must be newer than the account creation time and <=90 seconds old.

## Persistence and controls

An OS file lock prevents duplicate workers. SQLite transactions serialize wallet
and event changes. `paper.sqlite3` contains candles, the separate account and an
append-only application event ledger. `status.json` is an atomically replaced
readable snapshot; the database is authoritative. `worker.pid`, stdout/stderr
logs and the status heartbeat permit health checks. An old status snapshot is
not evidence of a running process. Files reside in the existing local workspace
and follow its existing synchronization policy.

Each hourly opportunity logs its rejection or entry reason and input features.
Entry/exit events preserve book evidence, prices, fees, quantity, original plan
and net P&L. Stops get an evidence-limited ordinary-loss/unknown classification;
the worker never attributes news causation without evidence or edits parameters.

Freshness checks require a reasonable server/local clock match, finalized
continuous candles, locally recent book responses taking <=3 seconds, increasing
update IDs and valid noncrossed depth. Incomplete inputs block entries. Missing
book data cannot fabricate an exit fill and is logged. Exits still run using
available books when candle features fail. Marked equity with stale inputs is
flagged by `data_healthy=false`; it is not reliable current valuation.

Entry estimates sweep displayed asks, add 5 bps adverse execution allowance and
charge 10 bps fees. Quantity is rounded down to LOT_SIZE, instrument status and
spot permission are checked, and notional filters are enforced. Stop/target
levels are rounded down to price ticks BEFORE rechecking admission. Spreads
above 10 bps block entry. Quotes, depth or filters can change before an actual
order; no executable-fill claim is made.

Exits sweep displayed bids plus adverse allowance and fees. Fully completed
15m bars starting after entry provide conservative stop-first reconciliation
when the observed current bid misses a past stop. Such fills are explicitly
labeled `CONSERVATIVE_CANDLE_RECONCILIATION`, never presented as observed trades.
The entry's partial candle is excluded to avoid using a pre-entry low. Intrabar
excursions between polls, particularly in that partial candle, may be missed;
targets are recognized from sampled bid quotes, not optimistic historical highs.
This asymmetry is conservative but not a tick-level broker emulator. A missed
monitoring interval is separately recorded and blocks new entries.

News/calendar vetoes, true limit-order queues, partial exchange fills, fee-asset
balances and actual account fee tiers are unavailable. This forward ledger is
experimental evidence, not sufficient validation for live deployment. The
candidate may produce very few trades, and no trade count or return is promised.
