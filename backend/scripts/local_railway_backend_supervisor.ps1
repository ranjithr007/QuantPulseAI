param(
    [string]$DatabaseUrlFile = '',
    [int]$CheckIntervalSeconds = 15,
    [switch]$Once
)

$ErrorActionPreference = 'Stop'
$backendRoot = Split-Path -Parent $PSScriptRoot
$repoRoot = Split-Path -Parent $backendRoot
if (-not $DatabaseUrlFile) { $DatabaseUrlFile = Join-Path $repoRoot '.env.pg3' }
$python = Join-Path $backendRoot 'venv\Scripts\python.exe'
$runtimeRoot = Join-Path $backendRoot 'runtime'
$stdout = Join-Path $runtimeRoot 'backend.out.log'
$stderr = Join-Path $runtimeRoot 'backend.err.log'
$log = Join-Path $runtimeRoot 'local-railway-backend-supervisor.log'
New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null

function Write-Status([string]$message) {
    Add-Content -LiteralPath $log -Value "$(Get-Date -Format o) $message"
    Write-Output $message
}

function Get-RailwayUrl {
    if (-not (Test-Path -LiteralPath $DatabaseUrlFile)) {
        throw "Database URL file not found: $DatabaseUrlFile"
    }
    $line = Get-Content -LiteralPath $DatabaseUrlFile |
        Where-Object { $_ -match '^QUANTPULSE_TARGET_DATABASE_URL=' } |
        Select-Object -First 1
    if (-not $line) { throw 'QUANTPULSE_TARGET_DATABASE_URL is missing.' }
    $value = $line.Substring('QUANTPULSE_TARGET_DATABASE_URL='.Length).Trim('"')
    $parsed = [uri]$value
    if ($parsed.Scheme -notin @('postgres', 'postgresql') -or
        $parsed.Host -in @('localhost', '127.0.0.1', '::1') -or
        -not $parsed.UserInfo) {
        throw 'The local backend requires the Railway PostgreSQL public URL.'
    }
    return $value
}

function Get-ListenerPid {
    $match = netstat -ano |
        Select-String '^\s*TCP\s+127\.0\.0\.1:8000\s+\S+\s+LISTENING\s+\d+' |
        Select-Object -First 1
    if (-not $match) { return $null }
    return [int](($match.ToString() -split '\s+')[-1])
}

function Test-Backend {
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health/dependencies' -TimeoutSec 8
        return ($health.active_database_scheme -eq 'postgresql' -and
            -not $health.using_sqlite_fallback)
    }
    catch { return $false }
}

function Stop-ManagedBackend {
    $listenerPid = Get-ListenerPid
    if (-not $listenerPid) { return }
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$listenerPid"
    if (-not $process -or $process.CommandLine -notmatch 'uvicorn app\.main:app') {
        throw "Port 8000 is owned by an unexpected process: $listenerPid"
    }
    Stop-Process -Id $listenerPid -Force
    Start-Sleep -Seconds 2
}

function Start-ManagedBackend {
    $env:QUANTPULSE_DATABASE_URL = Get-RailwayUrl
    $env:QUANTPULSE_START_SCHEDULER = 'false'
    $env:QUANTPULSE_START_LIVE_MARKET = 'false'
    Start-Process -FilePath $python -ArgumentList @(
        '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000'
    ) -WorkingDirectory $backendRoot -WindowStyle Hidden `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    Write-Status 'Started local backend using Railway PostgreSQL.'
}

$mutex = [System.Threading.Mutex]::new($false, 'Global\QuantPulseAILocalRailwayBackend')
if (-not $mutex.WaitOne(0)) { exit 0 }
try {
    $failures = 0
    while ($true) {
        if (Test-Backend) {
            $failures = 0
        }
        else {
            $failures++
            if ($failures -ge 2 -or -not (Get-ListenerPid)) {
                Stop-ManagedBackend
                Start-ManagedBackend
                $failures = 0
            }
        }
        if ($Once) { break }
        Start-Sleep -Seconds $CheckIntervalSeconds
    }
}
finally {
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
