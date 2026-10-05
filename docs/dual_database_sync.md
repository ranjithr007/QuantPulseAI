# Railway and local PostgreSQL data synchronization

The application uses one SQLAlchemy database per process. The intended online
configuration makes Railway PostgreSQL the writer for both the Railway and local
applications. A separate PostgreSQL instance on the local PC subscribes to a
Railway publication and receives committed changes. This is an asynchronous
copy: Railway can commit while the PC is offline, and the local copy catches up
after reconnecting as long as Railway still retains the required WAL.

SQL Server LocalDB remains the source for the pre-existing local history until
its rows are reconciled. Independent LocalDB and Railway IDs often name
different records. A plain upsert on primary key would lose distinct trades and
misattach child records.

## Agreed behavior

- Both the local application and Railway application may generate data.
- Existing local-only rows must be preserved and merged into Railway.
- Railway wins when the same logical row was independently changed on both sides.
- When local storage is offline, writes continue in Railway and local storage
  catches up when it reconnects.
- Online replication starts after Railway commits. This does **not** guarantee
  an immediate atomic dual write. A successful Railway write can precede the
  local copy, and a long offline period can require a fresh initial copy.

## Current installation (2026-10-05)

1. SQL Server LocalDB `QuantPulseAI` received a copy-only backup at
   `D:\QuantPulseAI-backups\QuantPulseAI-before-dual-db-20261005.bak`.
   `RESTORE VERIFYONLY WITH CHECKSUM` passed. The backup was also restored as
   read-only `QuantPulseAI_Migration` for a stable source. The original database
   has not been deleted.
2. A Railway on-demand volume backup was created successfully at 11:16 IST.
   The attempted direct `pg_dump` over the public proxy was interrupted and is
   **not** a valid backup.
3. Railway PostgreSQL was restarted with `wal_level=logical`. It publishes all
   current tables through `quantpulse_local_mirror`. The subscriber's WAL
   retention cap is 8 GB (`max_slot_wal_keep_size`), limiting unbounded growth
   when the PC is offline.
4. A separate PostgreSQL 18 instance runs on `127.0.0.1:5433` from
   `D:\PostgreSQL\quantpulse_mirror_data`; database `quantpulse_mirror` receives
   the Railway publication. The existing PostgreSQL instance on port 5432 and
   `D:\PostgreSQL\data` are untouched. A Windows logon task named
   `QuantPulseAI Local Mirror` starts the subscriber after a reboot.
5. The read-only LocalDB snapshot has been copied to `legacy_local` inside the
   separate local PostgreSQL database. The replicated Railway tables are in
   `public`, so legacy staging cannot overwrite live Railway rows. This is an
   archive and analysis step; the historical merge is not yet complete.

## Inspection

Keep Railway's external connection string in ignored `.env.pg3` and passwords
in protected local files; do not commit either. Run from the repository root:

```powershell
& backend\venv\Scripts\python.exe backend\scripts\setup_local_logical_mirror.py status
& backend\venv\Scripts\python.exe backend\scripts\analyze_legacy_merge.py --table paper_trades --cross-id
```

To rerun the independent schema preflight, set
`QUANTPULSE_SOURCE_DATABASE_URL` and `QUANTPULSE_TARGET_DATABASE_URL`, then run:

```powershell
& backend\venv\Scripts\python.exe backend\scripts\audit_dual_database_sync.py
& backend\venv\Scripts\python.exe backend\scripts\audit_dual_database_sync.py --scan-conflicts --table paper_trades
```

The first command checks schemas only. The second compares one table and
streams rows to count local-only, Railway-only, matching, and conflicting
primary keys. Repeat `--table` for multiple selected tables; omit it to scan
all shared tables. `--count-rows` adds exact row counts and can be slow. The
schema audit found 48 shared application tables with compatible column and
primary-key shapes.

## Remaining rollout work

1. Let the remaining Railway initial table copy finish and verify counts.
2. Resolve natural-key matches, unrelated ID collisions, and child references.
   Apply Railway-wins to the same logical record; preserve distinct local-only
   records with remapped IDs. Keep the read-only snapshot and backups intact.
3. The local API has been switched to Railway PostgreSQL after the frozen
   cutover backup. Its Railway backend supervisor verifies the PostgreSQL
   database scheme and avoids running a second scheduler against the same
   Railway database. The old LocalDB supervisor is disabled.
4. Verify local and Railway application writes, subscriber lag, and reconnect
   behavior. PostgreSQL logical replication does not replicate schema changes
   or sequence state; apply new migrations to both sides and recheck sequences.
5. If the local subscriber exceeds the retained WAL after a long outage,
   reinitialize it from Railway rather than writing to stale local tables.

The local subscriber is a mirror, not a second writable primary. The historical
merge remains pending until reference mappings are reviewed.
