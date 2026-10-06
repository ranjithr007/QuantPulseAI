# Railway storage cap

`backend/scripts/archive_trim_railway.py` keeps the oldest `decision_snapshots`
rows in the local PostgreSQL mirror before deleting the same verified IDs from
Railway. Railway remains authoritative for the rows that are copied. The
checkpoint is stored in `legacy_local._railway_trim_progress`, so an interrupted
run resumes without losing the verified local copy.

## Run a trim

Run a dry plan first:

```powershell
backend\venv\Scripts\python.exe backend\scripts\archive_trim_railway.py plan `
  --max-gb 25 --target-gb 24 --safety-factor 1.20
```

Start or resume the verified archive and delete job:

```powershell
backend\venv\Scripts\python.exe backend\scripts\archive_trim_railway.py trim `
  --max-gb 25 --target-gb 24 --safety-factor 1.20 --batch-size 10000
```

The job prints processed rows, remaining rows, completion percentage, and the
current Railway database size after each batch. It transfers only IDs that are
missing locally, then verifies the complete batch locally before deleting the
Railway IDs.

## Physical volume usage

`DELETE` makes pages reusable but normally does not reduce the volume metric.
After a trim, the table must be rewritten during a maintenance window:

```sql
VACUUM (FULL, ANALYZE) public.decision_snapshots;
```

`VACUUM FULL` takes an exclusive table lock and needs temporary free space. If
the volume is too full to rewrite the table, temporarily resize the Railway
volume first. A long-term hard cap should use date partitions and drop archived
partitions after the local copy is verified; dropping a partition releases its
files without rewriting the remaining data.

## Other historical tables

The global policy for the remaining historical evidence tables is a **28 GB
Railway database limit**, with a 27 GB target reserve. Run this job after the
decision snapshot trim has finished:

```powershell
backend\venv\Scripts\python.exe backend\scripts\archive_trim_railway_tables.py `
  --max-gb 28 --target-gb 27 --batch-size 5000
```

Rows are stored in local `legacy_local.archive_<table>` tables before the
Railway delete. The default candidates are large market and pipeline history
tables. Paper trades, wallet ledger, trade plans, strategy configuration, and
other account state remain protected.
