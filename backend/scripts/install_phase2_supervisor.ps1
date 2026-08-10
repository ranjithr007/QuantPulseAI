param(
    [string]$TaskName = "QuantPulseAI-Phase2-Supervisor",
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$SupervisorPath = Join-Path $PSScriptRoot "phase2_supervisor.ps1"

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Output "Removed scheduled task $TaskName."
    exit 0
}

if (-not (Test-Path -LiteralPath $SupervisorPath)) {
    throw "Supervisor script not found: $SupervisorPath"
}

$powerShellPath = (
    Get-Command powershell.exe -ErrorAction Stop
).Source
$arguments = (
    '-NoProfile -ExecutionPolicy Bypass -File "{0}"' -f $SupervisorPath
)
$action = New-ScheduledTaskAction `
    -Execute $powerShellPath `
    -Argument $arguments
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description (
        "Keeps QuantPulseAI LocalDB, backend, scheduler, live feed, " +
        "and Phase 2 paper pipeline healthy."
    ) `
    -User "$env:USERDOMAIN\$env:USERNAME" `
    -RunLevel Limited `
    -Force | Out-Null

Start-ScheduledTask -TaskName $TaskName
Write-Output "Installed and started scheduled task $TaskName."
