param(
    [string]$DataDirectory = 'D:\PostgreSQL\quantpulse_mirror_data',
    [string]$LogFile = 'D:\PostgreSQL\quantpulse_mirror.log',
    [string]$PgBin = 'D:\PostgreSQL\bin',
    [int]$Port = 5433
)

$ErrorActionPreference = 'Stop'
$pgctl = Join-Path $PgBin 'pg_ctl.exe'
& $pgctl --pgdata=$DataDirectory status *> $null
if ($LASTEXITCODE -eq 0) { exit 0 }
& $pgctl --pgdata=$DataDirectory --log=$LogFile --options="-p $Port -c listen_addresses=127.0.0.1 -c max_logical_replication_workers=12 -c max_worker_processes=16" start
if ($LASTEXITCODE -ne 0) { throw "Local mirror failed to start with exit code $LASTEXITCODE" }
