# LocalDB and Railway data synchronization

The application currently uses one SQLAlchemy database per process. Local development
defaults to SQL Server LocalDB, while Railway uses PostgreSQL. Running both
applications independently creates separate primary-key sequences and can produce
different records with the same ID. Connecting a second engine to every `commit()`
would not provide an atomic dual write and would miss some direct SQL writes.

## Agreed behavior

- Both the local application and Railway application may generate data.
- Existing local-only rows must be preserved and merged into Railway.
- Railway wins when the same logical row was independently changed on both sides.
- When local storage is offline, writes continue in Railway and local storage
  catches up when it reconnects.
- The online target is immediate local acknowledgement. If local storage is
  unavailable, the Railway write succeeds and remains queued for local replay.
  This cannot be an atomic two-database transaction: a successful Railway write
  can precede the local copy.

## Safe rollout sequence

1. Restore access to the existing `MSSQLLocalDB` instance and back up its
   `QuantPulseAI` database. Do not create a replacement empty database over it.
2. Obtain Railway PostgreSQL's external connection string (`DATABASE_PUBLIC_URL`)
   or a Railway CLI tunnel. Keep credentials in environment variables or a
   secrets manager, never in this repository.
3. From `backend`, set `QUANTPULSE_SOURCE_DATABASE_URL` to the LocalDB SQLAlchemy
   URL and `QUANTPULSE_TARGET_DATABASE_URL` to Railway's external PostgreSQL URL.
   Run the read-only preflight:

   ```powershell
   py scripts/audit_dual_database_sync.py --scan-conflicts
   ```

   The scan checks every shared table and streams rows to count local-only,
   Railway-only, matching, and conflicting primary keys. It reports key samples
   but never prints connection strings or row contents. It makes no database
   changes. Without `--scan-conflicts`, it checks schemas and row counts only.
4. Review key collisions and foreign-key references before merging existing
   local-only rows. A same-numbered ID might represent two unrelated records;
   blindly applying “Railway wins” to that collision can corrupt child records.
5. Only after the initial merge is reconciled, point both application processes
   at Railway PostgreSQL and run a local replication agent that copies committed
   Railway changes into LocalDB. It must maintain a durable change checkpoint,
   handle deletes, and replay after disconnection. The agent and change feed are
   **not yet implemented or enabled**.

The preflight is a prerequisite for designing the initial merge. It is not a
replication service and does not make the current application dual-write.
