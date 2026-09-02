param(
    [string]$ApiBaseUrl = "http://127.0.0.1:8000",
    [string]$LocalDbInstance = "MSSQLLocalDB",
    [int]$CheckIntervalSeconds = 15,
    [int]$FailureThreshold = 2,
    [int]$PipelineStuckMinutes = 30,
    [int]$CoverageGraceMinutes = 15,
    [int]$CoverageWindowHours = 24,
    [switch]$Once
)

$ErrorActionPreference = "Stop"
$BackendRoot = Split-Path -Parent $PSScriptRoot
$RuntimeRoot = Join-Path $BackendRoot "runtime"
$LogPath = Join-Path $RuntimeRoot "phase2-supervisor.log"
$StatusPath = Join-Path $RuntimeRoot "phase2-supervisor-status.json"
$StdoutPath = Join-Path $RuntimeRoot "backend.out.log"
$StderrPath = Join-Path $RuntimeRoot "backend.err.log"
$PythonPath = Join-Path $BackendRoot "venv\Scripts\python.exe"

New-Item -ItemType Directory -Path $RuntimeRoot -Force | Out-Null

$mutex = [System.Threading.Mutex]::new(
    $false,
    "Global\QuantPulseAIPhase2Supervisor"
)
if (-not $mutex.WaitOne(0)) {
    Write-Output "QuantPulseAI Phase 2 supervisor is already running."
    exit 0
}

function Write-SupervisorLog {
    param(
        [string]$Message,
        [string]$Level = "INFO"
    )
    $line = "{0} [{1}] {2}" -f (
        Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"
    ), $Level, $Message
    Add-Content -LiteralPath $LogPath -Value $line
    Write-Output $line
}

function Write-SupervisorStatus {
    param([hashtable]$Status)
    $Status["observed_at"] = (Get-Date).ToUniversalTime().ToString("o")
    $temporaryPath = "$StatusPath.tmp"
    $Status | ConvertTo-Json -Depth 6 |
        Set-Content -LiteralPath $temporaryPath -Encoding UTF8
    Move-Item -LiteralPath $temporaryPath -Destination $StatusPath -Force
}

function Invoke-Api {
    param(
        [string]$Path,
        [string]$Method = "Get",
        [int]$TimeoutSeconds = 15
    )
    Invoke-RestMethod `
        -Uri "$ApiBaseUrl$Path" `
        -Method $Method `
        -TimeoutSec $TimeoutSeconds
}

function Write-RecoveryEvent {
    param(
        [string]$Status,
        [string]$Reason,
        [string]$GapSignature,
        [int]$MissingBefore,
        [int]$MissingAfter = -1,
        [string]$ErrorMessage = $null
    )

    $payload = @{
        status = $Status
        reason = $Reason
        gap_signature = $GapSignature
        missing_before = $MissingBefore
        missing_after = if ($MissingAfter -ge 0) { $MissingAfter } else { $null }
        repair_action = "persist_official_watchlist_stack_once"
        error = $ErrorMessage
        observed_at = (Get-Date).ToUniversalTime().ToString("o")
    }

    try {
        Invoke-RestMethod `
            -Uri "$ApiBaseUrl/paper-trade/recovery-events" `
            -Method Post `
            -ContentType "application/json" `
            -Body ($payload | ConvertTo-Json -Depth 5) `
            -TimeoutSec 15 | Out-Null
    }
    catch {
        Write-SupervisorLog (
            "Could not persist recovery history event ${Status}: " +
            $_.Exception.Message
        ) "WARN"
    }
}

function Ensure-DailyEvidenceCheckpoint {
    param([hashtable]$Health)

    $checkpointDate = Get-Date -Format "yyyy-MM-dd"
    if ($script:lastCheckpointDate -eq $checkpointDate) {
        return "current"
    }
    $payload = @{
        checkpoint_date = $checkpointDate
        observed_at = (Get-Date).ToUniversalTime().ToString("o")
    }
    try {
        $response = Invoke-RestMethod `
            -Uri "$ApiBaseUrl/paper-trade/evidence-checkpoints" `
            -Method Post `
            -ContentType "application/json" `
            -Body ($payload | ConvertTo-Json) `
            -TimeoutSec 120
        if ($response.status -in @("RECORDED", "EXISTS")) {
            $script:lastCheckpointDate = $checkpointDate
            Write-SupervisorLog (
                "Phase 2 daily evidence checkpoint ${checkpointDate}: " +
                $response.status
            )
            return ([string]$response.status).ToLowerInvariant()
        }
        return "unexpected_response"
    }
    catch {
        Write-SupervisorLog (
            "Daily evidence checkpoint failed: $($_.Exception.Message)"
        ) "WARN"
        return "retry_pending"
    }
}

function Start-CanonicalDatabase {
    Write-SupervisorLog "Starting LocalDB instance $LocalDbInstance."
    $output = & sqllocaldb start $LocalDbInstance 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "LocalDB start failed: $($output -join ' ')"
    }
}

function Get-BackendListenerPid {
    $listener = netstat -ano |
        Select-String ":8000\s+.*LISTENING" |
        Select-Object -First 1
    if (-not $listener) {
        return $null
    }
    $parts = ($listener.ToString() -split "\s+") |
        Where-Object { $_ }
    return [int]$parts[-1]
}

function Stop-Backend {
    $listenerPid = Get-BackendListenerPid
    if ($null -eq $listenerPid) {
        return
    }
    Write-SupervisorLog "Stopping unhealthy backend PID $listenerPid." "WARN"
    Stop-Process -Id $listenerPid -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

function Start-Backend {
    if (-not (Test-Path -LiteralPath $PythonPath)) {
        throw "Backend Python runtime not found: $PythonPath"
    }

    $env:QUANTPULSE_START_SCHEDULER = "true"
    $env:QUANTPULSE_SCHEDULER_JOBS = (
        "deterministic_pipeline,derivative,candle_completeness,pipeline_retention"
    )
    $env:QUANTPULSE_START_LIVE_MARKET = "true"

    Write-SupervisorLog "Starting QuantPulseAI backend."
    Start-Process `
        -FilePath $PythonPath `
        -ArgumentList @(
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000"
        ) `
        -WorkingDirectory $BackendRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $StdoutPath `
        -RedirectStandardError $StderrPath
}

function Wait-ForCanonicalBackend {
    param([int]$TimeoutSeconds = 150)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $dependencies = Invoke-Api "/health/dependencies"
            if (
                $dependencies.active_database_scheme -eq "mssql" -and
                -not $dependencies.using_sqlite_fallback
            ) {
                return $true
            }
        }
        catch {
            # Startup is still in progress.
        }
        Start-Sleep -Seconds 3
    }
    return $false
}

function Get-Phase2Health {
    $dependencies = Invoke-Api "/health/dependencies"
    $scheduler = Invoke-Api "/scheduler/status"
    $pipeline = Invoke-Api "/health/pipeline"
    $live = Invoke-Api "/live/status"
    $coverageStatus = "UNAVAILABLE"
    $coveragePercent = $null
    $coverageExpected = 0
    $coverageRecorded = 0
    $coverageMissing = 0
    $coverageGapSignature = $null

    try {
        $opportunities = Invoke-Api (
            "/paper-trade/opportunities?since_hours=$CoverageWindowHours" +
            "&scheduler_grace_minutes=$CoverageGraceMinutes"
        )
        if ($opportunities.status -eq "OK" -and $opportunities.coverage) {
            $coverage = $opportunities.coverage
            $coverageStatus = [string]$coverage.status
            $coveragePercent = $coverage.coverage_percent
            $coverageExpected = [int]$coverage.expected_evaluations
            $coverageRecorded = [int]$coverage.recorded_evaluations
            $coverageMissing = [int]$coverage.missing_evaluations
            if ($coverageMissing -gt 0) {
                $coverageGapSignature = (
                    $coverage.missing | ConvertTo-Json -Compress -Depth 5
                )
            }
        }
    }
    catch {
        # Coverage is reported separately and must not make runtime health fail.
    }

    $canonicalDatabase = (
        $dependencies.active_database_scheme -eq "mssql" -and
        -not $dependencies.using_sqlite_fallback
    )
    $schedulerRunning = [bool]$scheduler.running
    $liveRunning = [bool]$live.running
    $pipelineStatus = [string]$pipeline.pipeline.status
    $pipelineStartedAt = $pipeline.pipeline.started_at
    $pipelineStuck = $false

    if ($pipelineStatus -eq "RUNNING" -and $pipelineStartedAt) {
        $parsedPipelineStart = [datetime]$pipelineStartedAt
        if ($parsedPipelineStart.Kind -eq [DateTimeKind]::Unspecified) {
            $parsedPipelineStart = [datetime]::SpecifyKind(
                $parsedPipelineStart,
                [DateTimeKind]::Utc
            )
        }
        $pipelineAge = (
            (Get-Date).ToUniversalTime() -
            $parsedPipelineStart.ToUniversalTime()
        )
        $pipelineStuck = (
            $pipelineAge.TotalMinutes -gt $PipelineStuckMinutes
        )
    }

    if ($live.running -and $live.last_tick_at) {
        $initialLastTick = [datetime]$live.last_tick_at
        if ($initialLastTick.Kind -eq [DateTimeKind]::Unspecified) {
            $initialLastTick = [datetime]::SpecifyKind(
                $initialLastTick,
                [DateTimeKind]::Utc
            )
        }
        $initialLiveAge = (
            (Get-Date).ToUniversalTime() -
            $initialLastTick.ToUniversalTime()
        )
        if ($initialLiveAge.TotalSeconds -gt 60) {
            # Reading status triggers the service's REST refresh fallback.
            Start-Sleep -Seconds 2
            $live = Invoke-Api "/live/status"
        }
    }

    $liveLastTickAt = $live.last_tick_at
    $liveDataFresh = $false
    if ($liveLastTickAt) {
        $parsedLastTick = [datetime]$liveLastTickAt
        if ($parsedLastTick.Kind -eq [DateTimeKind]::Unspecified) {
            $parsedLastTick = [datetime]::SpecifyKind(
                $parsedLastTick,
                [DateTimeKind]::Utc
            )
        }
        $liveAge = (
            (Get-Date).ToUniversalTime() -
            $parsedLastTick.ToUniversalTime()
        )
        $liveDataFresh = $liveAge.TotalSeconds -le 60
    }

    return @{
        healthy = (
            $canonicalDatabase -and
            $schedulerRunning -and
            $liveRunning -and
            -not $pipelineStuck
        )
        canonical_database = $canonicalDatabase
        database_scheme = $dependencies.active_database_scheme
        sqlite_fallback = [bool]$dependencies.using_sqlite_fallback
        scheduler_running = $schedulerRunning
        pipeline_status = $pipelineStatus
        pipeline_ready = [bool]$pipeline.ready
        paper_execution_allowed = [bool]$pipeline.paper_execution_allowed
        pipeline_stuck = $pipelineStuck
        live_running = $liveRunning
        live_connected = [bool]$live.connected
        live_data_fresh = $liveDataFresh
        live_data_degraded = ($liveRunning -and -not $liveDataFresh)
        live_state = $live.state
        live_last_tick_at = $live.last_tick_at
        live_error = $live.last_error
        api_responsive = $true
        opportunity_coverage_status = $coverageStatus
        opportunity_coverage_percent = $coveragePercent
        opportunity_coverage_expected = $coverageExpected
        opportunity_coverage_recorded = $coverageRecorded
        opportunity_coverage_missing = $coverageMissing
        opportunity_coverage_gap_signature = $coverageGapSignature
    }
}

function Repair-OpportunityCoverage {
    param([hashtable]$Health)

    if ($Health.opportunity_coverage_status -ne "GAPS_DETECTED") {
        return "not_required"
    }
    $gapSignature = [string]$Health.opportunity_coverage_gap_signature
    if (
        $gapSignature -and
        $script:lastCoverageRepairKey -eq $gapSignature
    ) {
        return "already_attempted"
    }
    $script:lastCoverageRepairKey = $gapSignature

    Write-SupervisorLog (
        "Opportunity coverage gap detected: " +
        "$($Health.opportunity_coverage_missing) missing evaluation(s). " +
        "Running one bounded persistence retry."
    ) "WARN"
    Write-RecoveryEvent `
        -Status "ATTEMPTED" `
        -Reason "One bounded opportunity coverage retry started." `
        -GapSignature $gapSignature `
        -MissingBefore $Health.opportunity_coverage_missing

    try {
        $recoveryPayload = @{
            missing = @($gapSignature | ConvertFrom-Json)
        }
        Invoke-RestMethod `
            -Uri "$ApiBaseUrl/signals/watchlist/recover-opportunity-gaps" `
            -Method Post `
            -ContentType "application/json" `
            -Body ($recoveryPayload | ConvertTo-Json -Depth 8) `
            -TimeoutSec 300 | Out-Null
        Start-Sleep -Seconds 3

        $verification = Invoke-Api (
            "/paper-trade/opportunities?since_hours=$CoverageWindowHours" +
            "&scheduler_grace_minutes=$CoverageGraceMinutes"
        ) "Get" 30
        $remaining = [int]$verification.coverage.missing_evaluations
        if ($remaining -eq 0) {
            Write-SupervisorLog "Opportunity coverage recovered after one retry."
            Write-RecoveryEvent `
                -Status "RECOVERED" `
                -Reason "Opportunity coverage recovered after one bounded retry." `
                -GapSignature $gapSignature `
                -MissingBefore $Health.opportunity_coverage_missing `
                -MissingAfter 0
            return "recovered"
        }

        Write-SupervisorLog (
            "Opportunity coverage remains incomplete after the bounded retry: " +
            "$remaining missing evaluation(s)."
        ) "ERROR"
        Write-RecoveryEvent `
            -Status "UNRESOLVED" `
            -Reason "Opportunity coverage remained incomplete after one bounded retry." `
            -GapSignature $gapSignature `
            -MissingBefore $Health.opportunity_coverage_missing `
            -MissingAfter $remaining
        return "unresolved"
    }
    catch {
        $retryError = $_.Exception.Message
        Write-SupervisorLog (
            "Opportunity coverage retry failed: $retryError"
        ) "ERROR"
        Write-RecoveryEvent `
            -Status "RETRY_FAILED" `
            -Reason "Opportunity coverage retry failed before verification." `
            -GapSignature $gapSignature `
            -MissingBefore $Health.opportunity_coverage_missing `
            -ErrorMessage $retryError
        return "retry_failed"
    }
}

function Repair-Phase2Runtime {
    param([hashtable]$Health)

    if (-not $Health.canonical_database) {
        Start-CanonicalDatabase
        Stop-Backend
        Start-Backend
        return
    }

    if (-not $Health.scheduler_running) {
        try {
            Invoke-Api "/scheduler/start" "Post" | Out-Null
            Write-SupervisorLog "Restarted scheduler through the API." "WARN"
            return
        }
        catch {
            Write-SupervisorLog "Scheduler API restart failed." "WARN"
        }
    }

    if (-not $Health.live_running) {
        try {
            Invoke-Api "/live/start" "Post" | Out-Null
            Write-SupervisorLog "Restarted live-market service." "WARN"
            return
        }
        catch {
            Write-SupervisorLog "Live-market API restart failed." "WARN"
        }
    }

    if ($Health.pipeline_stuck) {
        Write-SupervisorLog (
            "Pipeline exceeded the $PipelineStuckMinutes minute limit."
        ) "WARN"
    }

    Stop-Backend
    Start-Backend
}

$consecutiveFailures = 0
$script:lastCoverageRepairKey = $null
$script:apiUnresponsiveSince = $null
$script:lastCheckpointDate = $null

try {
    while ($true) {
        try {
            $health = Get-Phase2Health
            $script:apiUnresponsiveSince = $null
            $health["opportunity_coverage_repair"] = (
                Repair-OpportunityCoverage $health
            )
            $health["daily_evidence_checkpoint"] = (
                Ensure-DailyEvidenceCheckpoint $health
            )
            Write-SupervisorStatus $health

            if ($health.healthy) {
                $consecutiveFailures = 0
            }
            else {
                $consecutiveFailures += 1
                Write-SupervisorLog (
                    "Health check failed ($consecutiveFailures/" +
                    "$FailureThreshold): " +
                    ($health | ConvertTo-Json -Compress)
                ) "WARN"

                if (
                    -not $health.canonical_database -or
                    $consecutiveFailures -ge $FailureThreshold
                ) {
                    Repair-Phase2Runtime $health
                    if (-not (Wait-ForCanonicalBackend)) {
                        throw "Canonical backend did not become healthy."
                    }
                    $consecutiveFailures = 0
                }
            }
        }
        catch {
            $listenerPid = Get-BackendListenerPid
            if ($null -ne $listenerPid) {
                if ($null -eq $script:apiUnresponsiveSince) {
                    $script:apiUnresponsiveSince = Get-Date
                    Write-SupervisorLog (
                        "Backend listener is active but health APIs are busy; " +
                        "deferring restart for up to $PipelineStuckMinutes minutes."
                    ) "WARN"
                }

                $unresponsiveAge = (
                    (Get-Date) - $script:apiUnresponsiveSince
                )
                Write-SupervisorStatus @{
                    healthy = $false
                    api_responsive = $false
                    listener_active = $true
                    listener_pid = $listenerPid
                    api_unresponsive_minutes = [math]::Round(
                        $unresponsiveAge.TotalMinutes,
                        2
                    )
                    opportunity_coverage_status = "UNKNOWN_DURING_API_TIMEOUT"
                    opportunity_coverage_repair = "deferred_api_busy"
                }
                $consecutiveFailures = 0

                if (
                    $unresponsiveAge.TotalMinutes -gt
                    $PipelineStuckMinutes
                ) {
                    Write-SupervisorLog (
                        "Backend API remained unresponsive beyond the " +
                        "$PipelineStuckMinutes minute limit."
                    ) "ERROR"
                    Stop-Backend
                    Start-Backend
                    $script:apiUnresponsiveSince = $null
                }
            }
            else {
                $script:apiUnresponsiveSince = $null
                $consecutiveFailures += 1
                Write-SupervisorLog $_.Exception.Message "ERROR"

                if ($consecutiveFailures -ge $FailureThreshold) {
                    Start-CanonicalDatabase
                    Start-Backend
                    if (-not (Wait-ForCanonicalBackend)) {
                        Write-SupervisorLog (
                            "Backend recovery timed out; retrying next cycle."
                        ) "ERROR"
                    }
                    $consecutiveFailures = 0
                }
            }
        }

        if ($Once) {
            break
        }
        Start-Sleep -Seconds $CheckIntervalSeconds
    }
}
finally {
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
