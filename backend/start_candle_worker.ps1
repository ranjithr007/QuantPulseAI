param(
    [switch]$Foreground
)

$ErrorActionPreference = "Stop"
$backendRoot = $PSScriptRoot
$python = Join-Path $backendRoot "venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Virtual-environment Python was not found at $python"
}

$existing = Get-CimInstance Win32_Process |
    Where-Object {
        $_.Name -eq "python.exe" -and
        $_.CommandLine -like "*app.worker*"
    } |
    Select-Object -First 1

if ($existing) {
    Write-Output "A QuantPulse worker is already running (PID $($existing.ProcessId))."
    exit 0
}

$env:QUANTPULSE_PROCESS_ROLE = "worker"
$env:QUANTPULSE_START_SCHEDULER = "true"
$env:QUANTPULSE_START_LIVE_MARKET = "false"
$env:QUANTPULSE_SCHEDULER_JOBS = "market,candle_completeness"
$env:PYTHONUNBUFFERED = "1"

if ($Foreground) {
    & $python -u -m app.worker
    exit $LASTEXITCODE
}

$stdout = Join-Path $backendRoot "market-worker.stdout.log"
$stderr = Join-Path $backendRoot "market-worker.stderr.log"
$worker = Start-Process `
    -FilePath $python `
    -ArgumentList "-u", "-m", "app.worker" `
    -WorkingDirectory $backendRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr `
    -PassThru

Write-Output "Started candle-only QuantPulse worker (PID $($worker.Id))."
Write-Output "Jobs: market,candle_completeness"
Write-Output "Logs: $stdout and $stderr"

