# Candle-only worker runbook

## Purpose

`start_candle_worker.ps1` runs only the market collector and candle-completeness
monitor. It does not run fusion, risk, paper-trade, or execution stages.

## Start

From the backend directory:

```powershell
.\start_candle_worker.ps1
```

The script refuses to start a second `app.worker` process. For interactive
diagnostics, use `-Foreground`.

## Verify

Check the process and logs:

```powershell
Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -like "*app.worker*" }

Get-Content .\market-worker.stdout.log -Tail 100
Get-Content .\market-worker.stderr.log -Tail 100
```

Check the sealed holdout's candle-only progress without reading outcomes:

```powershell
.\venv\Scripts\python.exe -m scripts.check_directional_risk_holdout_readiness
```

## Runtime boundary

The worker environment is deliberately restricted to:

```text
QUANTPULSE_SCHEDULER_JOBS=market,candle_completeness
QUANTPULSE_START_LIVE_MARKET=false
```

Use the full API/worker deployment procedure separately when the application
pipeline is intended to run. Do not broaden this worker's job list merely to
collect holdout candles.

