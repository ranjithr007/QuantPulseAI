$ErrorActionPreference = "Stop"

if (-not $env:SETUPTOOLS_USE_DISTUTILS) {
    $env:SETUPTOOLS_USE_DISTUTILS = "stdlib"
}

if (-not $env:QUANTPULSE_START_SCHEDULER) {
    $env:QUANTPULSE_START_SCHEDULER = "false"
}

if (-not $env:QUANTPULSE_SCHEDULER_JOBS) {
    $env:QUANTPULSE_SCHEDULER_JOBS = "market"
}

uvicorn app.main:app --reload
