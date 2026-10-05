param([string]$TaskName = 'QuantPulseAI Local Mirror')

$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PSScriptRoot 'start_local_mirror.ps1'
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute (Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe') -Argument (
    '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}"' -f $scriptPath
)
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -Hidden
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal `
    -Settings $settings -Description 'Starts the local PostgreSQL Railway mirror.' -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Output "Started scheduled task $TaskName."
