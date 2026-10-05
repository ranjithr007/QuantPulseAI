param(
    [string]$PgBin = 'D:\PostgreSQL\bin',
    [int]$LocalPort = 5433,
    [string]$LocalDatabase = 'quantpulse_mirror'
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$line = Get-Content -LiteralPath (Join-Path $repoRoot '.env.pg3') |
    Where-Object { $_ -match '^QUANTPULSE_TARGET_DATABASE_URL=' } |
    Select-Object -First 1
if (-not $line) { throw 'QUANTPULSE_TARGET_DATABASE_URL is missing from .env.pg3.' }
$url = [uri]$line.Substring('QUANTPULSE_TARGET_DATABASE_URL='.Length).Trim('"')
if ($url.Scheme -notin @('postgres', 'postgresql')) { throw 'Railway target must use PostgreSQL.' }
$credentials = $url.UserInfo.Split(':', 2)
if ($credentials.Count -ne 2 -or -not $credentials[1]) { throw 'Railway URL lacks a password.' }
$railwayHost = $url.Host
$railwayPort = [string]$url.Port
$railwayUser = [uri]::UnescapeDataString($credentials[0])
$railwayDatabase = $url.AbsolutePath.TrimStart('/')
$dumpPath = Join-Path $repoRoot 'backend\outputs\railway_schema.dump'
if (Test-Path -LiteralPath $dumpPath) { throw "Schema dump already exists: $dumpPath" }

$env:PGPASSWORD = [uri]::UnescapeDataString($credentials[1])
$env:PGSSLMODE = 'require'
try {
    & (Join-Path $PgBin 'pg_dump.exe') -w --host=$railwayHost --port=$railwayPort --username=$railwayUser --dbname=$railwayDatabase --format=custom --schema-only --no-owner --no-acl --file=$dumpPath
    if ($LASTEXITCODE -ne 0) { throw "pg_dump exited with code $LASTEXITCODE" }
}
finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    Remove-Item Env:PGSSLMODE -ErrorAction SilentlyContinue
}

$env:PGPASSWORD = [System.IO.File]::ReadAllText('D:\PostgreSQL\quantpulse_mirror_password.txt').Trim()
try {
    & (Join-Path $PgBin 'createdb.exe') -w --host=127.0.0.1 --port=$LocalPort --username=quantpulse_mirror $LocalDatabase
    if ($LASTEXITCODE -ne 0) { throw "createdb exited with code $LASTEXITCODE" }
    & (Join-Path $PgBin 'pg_restore.exe') -w --host=127.0.0.1 --port=$LocalPort --username=quantpulse_mirror --dbname=$LocalDatabase --exit-on-error --no-owner --no-acl --schema-only $dumpPath
    if ($LASTEXITCODE -ne 0) { throw "pg_restore exited with code $LASTEXITCODE" }
    & (Join-Path $PgBin 'psql.exe') -w --host=127.0.0.1 --port=$LocalPort --username=quantpulse_mirror --dbname=$LocalDatabase -Atqc "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'"
    if ($LASTEXITCODE -ne 0) { throw "Schema verification exited with code $LASTEXITCODE" }
}
finally { Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue }

Write-Output "Local mirror schema prepared in $LocalDatabase on port $LocalPort."
