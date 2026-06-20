param(
    [switch]$NoScheduler
)

$ErrorActionPreference = "Stop"

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
    $env:QUANTPULSE_SCHEDULER_JOBS = "market,feature,regime,orderflow,smc"
}

if (-not $env:QUANTPULSE_START_LIVE_MARKET) {
    $env:QUANTPULSE_START_LIVE_MARKET = "true"
}

if (-not $env:QUANTPULSE_LIVE_MARKET_SYMBOLS) {
    $env:QUANTPULSE_LIVE_MARKET_SYMBOLS = "BTCUSDT,ETHUSDT,XRPUSDT,SOLUSDT,BNBUSDT,DOGEUSDT"
}

uvicorn app.main:app --reload
