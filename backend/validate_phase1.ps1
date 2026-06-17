param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$Symbol = "BTCUSDT",
    [string]$Mode = "intraday"
)

$ErrorActionPreference = "Continue"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$RunDir = Join-Path $ProjectRoot "outputs\phase1_validation_runs\$Timestamp"
$Summary = New-Object System.Collections.Generic.List[object]

New-Item -ItemType Directory -Force -Path $RunDir | Out-Null

function Save-ValidationResult {
    param(
        [string]$Name,
        [string]$Method,
        [string]$Uri
    )

    $SafeName = $Name -replace "[^a-zA-Z0-9_-]", "_"
    $OutputPath = Join-Path $RunDir "$SafeName.json"
    $StartedAt = Get-Date

    try {
        if ($Method -eq "POST") {
            $Result = Invoke-RestMethod -Method POST -Uri $Uri
        }
        else {
            $Result = Invoke-RestMethod -Method GET -Uri $Uri
        }

        $Json = $Result | ConvertTo-Json -Depth 20
        $Json | Set-Content -Path $OutputPath -Encoding UTF8
        $Status = "PASS"
        $ErrorMessage = $null
    }
    catch {
        $ErrorObject = [PSCustomObject]@{
            name = $Name
            method = $Method
            uri = $Uri
            error = $_.Exception.Message
        }
        $ErrorObject | ConvertTo-Json -Depth 20 | Set-Content -Path $OutputPath -Encoding UTF8
        $Status = "FAIL"
        $ErrorMessage = $_.Exception.Message
    }

    $FinishedAt = Get-Date
    $Summary.Add([PSCustomObject]@{
        name = $Name
        method = $Method
        uri = $Uri
        status = $Status
        output = $OutputPath
        error = $ErrorMessage
        started_at = $StartedAt
        finished_at = $FinishedAt
    }) | Out-Null

    Write-Host ("[{0}] {1} {2}" -f $Status, $Method, $Name)
}

Write-Host "QuantPulseAI Phase 1 validation started"
Write-Host "Base URL: $BaseUrl"
Write-Host "Symbol: $Symbol"
Write-Host "Mode: $Mode"
Write-Host "Output: $RunDir"

Save-ValidationResult "health" "GET" "$BaseUrl/health"
Save-ValidationResult "scheduler_jobs" "GET" "$BaseUrl/scheduler/jobs"
Save-ValidationResult "signal_current" "GET" "$BaseUrl/signals/$Symbol"
Save-ValidationResult "master_ai_current" "GET" "$BaseUrl/master-ai/$Symbol"
Save-ValidationResult "watchlist_full" "GET" "$BaseUrl/signals/watchlist?mode=$Mode"
Save-ValidationResult "watchlist_ready" "GET" "$BaseUrl/signals/watchlist?mode=$Mode&status=READY"
Save-ValidationResult "watchlist_near_ready" "GET" "$BaseUrl/signals/watchlist?mode=$Mode&failed_max=1"
Save-ValidationResult "diagnostics_5m" "GET" "$BaseUrl/signals/$Symbol/diagnostics?timeframe=5m"
Save-ValidationResult "diagnostics_15m" "GET" "$BaseUrl/signals/$Symbol/diagnostics?timeframe=15m"
Save-ValidationResult "diagnostics_1h" "GET" "$BaseUrl/signals/$Symbol/diagnostics?timeframe=1h"
Save-ValidationResult "diagnostics_4h" "GET" "$BaseUrl/signals/$Symbol/diagnostics?timeframe=4h"
Save-ValidationResult "diagnostics_1d" "GET" "$BaseUrl/signals/$Symbol/diagnostics?timeframe=1d"
Save-ValidationResult "multi_timeframe" "GET" "$BaseUrl/signals/$Symbol/multi-timeframe?mode=$Mode"
Save-ValidationResult "multi_timeframe_swing" "GET" "$BaseUrl/signals/$Symbol/multi-timeframe?mode=swing"
Save-ValidationResult "multi_timeframe_position" "GET" "$BaseUrl/signals/$Symbol/multi-timeframe?mode=position"
Save-ValidationResult "entry_trigger" "GET" "$BaseUrl/signals/$Symbol/entry-trigger?mode=$Mode"
Save-ValidationResult "persist_ready_manual" "POST" "$BaseUrl/signals/watchlist/persist-ready?mode=$Mode"
Save-ValidationResult "persist_ready_scheduler" "POST" "$BaseUrl/scheduler/jobs/watchlist-persist/dry-run?execute=true"
Save-ValidationResult "trade_plan_open" "GET" "$BaseUrl/trade-plan/${Symbol}?status=OPEN"
Save-ValidationResult "risk_scheduler" "POST" "$BaseUrl/scheduler/jobs/risk/dry-run?execute=true"
Save-ValidationResult "risk_latest" "GET" "$BaseUrl/risk/$Symbol"
Save-ValidationResult "paper_candidates" "GET" "$BaseUrl/paper-trade/candidates"
Save-ValidationResult "paper_execute_manual" "POST" "$BaseUrl/paper-trade/execute-candidates"
Save-ValidationResult "paper_execute_scheduler" "POST" "$BaseUrl/scheduler/jobs/paper-trade-execute/dry-run?execute=true"
Save-ValidationResult "paper_monitor_scheduler" "POST" "$BaseUrl/scheduler/jobs/paper-trade-monitor/dry-run?execute=true"
Save-ValidationResult "paper_trades_open" "GET" "$BaseUrl/paper-trade/trades?status=OPEN"
Save-ValidationResult "paper_trades_closed" "GET" "$BaseUrl/paper-trade/trades?status=CLOSED"
Save-ValidationResult "paper_performance" "GET" "$BaseUrl/paper-trade/performance"
Save-ValidationResult "paper_performance_symbol" "GET" "$BaseUrl/paper-trade/performance?symbol=$Symbol"
Save-ValidationResult "pipeline_status" "GET" "$BaseUrl/pipeline/status?mode=$Mode"
Save-ValidationResult "pipeline_cycle_import" "POST" "$BaseUrl/scheduler/jobs/pipeline-cycle/dry-run"
Save-ValidationResult "pipeline_cycle_execute" "POST" "$BaseUrl/scheduler/jobs/pipeline-cycle/dry-run?execute=true"

$SummaryPath = Join-Path $RunDir "summary.json"
$Summary | ConvertTo-Json -Depth 20 | Set-Content -Path $SummaryPath -Encoding UTF8

$Failed = @($Summary | Where-Object { $_.status -eq "FAIL" })

Write-Host ""
Write-Host "Phase 1 validation complete"
Write-Host "Output folder: $RunDir"
Write-Host "Summary: $SummaryPath"
Write-Host ("Passed: {0}" -f ($Summary.Count - $Failed.Count))
Write-Host ("Failed: {0}" -f $Failed.Count)

if ($Failed.Count -gt 0) {
    Write-Host "Failed checks:"
    $Failed | ForEach-Object {
        Write-Host ("- {0}: {1}" -f $_.name, $_.error)
    }
    exit 1
}

exit 0
