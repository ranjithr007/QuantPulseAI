param(
    [switch]$NoScheduler,
    [switch]$Reload,
    [int]$MaxLegacyLogSizeMB = 25
)

$ErrorActionPreference = "Stop"

function Move-OversizedLegacyLog {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    $log = Get-Item -LiteralPath $Path
    if ($log.Length -le ($MaxLegacyLogSizeMB * 1MB)) {
        return
    }

    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $archivePath = "$Path.$timestamp.log"

    try {
        Move-Item -LiteralPath $Path -Destination $archivePath
        Write-Warning "Archived oversized legacy log to $archivePath"
    }
    catch {
        Write-Warning "Could not archive $Path. A running process may still have it open."
    }
}

Move-OversizedLegacyLog (Join-Path $PSScriptRoot "backend-run.err.log")
Move-OversizedLegacyLog (Join-Path $PSScriptRoot "backend-run.out.log")

if (-not $env:SETUPTOOLS_USE_DISTUTILS) {
    $env:SETUPTOOLS_USE_DISTUTILS = "stdlib"
}

if ($NoScheduler) {
    $env:QUANTPULSE_START_SCHEDULER = "false"
}
else {
    $env:QUANTPULSE_START_SCHEDULER = "true"
}

if (-not $env:QUANTPULSE_SCHEDULER_JOBS) {
    $env:QUANTPULSE_SCHEDULER_JOBS = "market,feature,regime,orderflow,smc,watchlist_persist,risk,paper_trade_execute,paper_trade_monitor"
}

if (-not $env:QUANTPULSE_START_LIVE_MARKET) {
    $env:QUANTPULSE_START_LIVE_MARKET = "true"
}

if (-not $env:QUANTPULSE_LIVE_MARKET_SYMBOLS) {
    $env:QUANTPULSE_LIVE_MARKET_SYMBOLS = "BTCUSDT,ETHUSDT,XRPUSDT,SOLUSDT,BNBUSDT,DOGEUSDT"
}

$uvicornArguments = @("app.main:app")
if ($Reload) {
    $uvicornArguments += "--reload"
}

& uvicorn @uvicornArguments
