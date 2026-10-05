param([string]$TaskName = 'QuantPulseAI Railway Backend')

$ErrorActionPreference = 'Stop'
$legacyTask = Get-ScheduledTask -TaskName 'QuantPulseAI-Phase2-Supervisor' -ErrorAction SilentlyContinue
if ($legacyTask -and $legacyTask.State -ne 'Disabled') {
    throw 'Disable the old LocalDB supervisor before installing the Railway backend task.'
}
$scriptPath = Join-Path $PSScriptRoot 'local_railway_backend_supervisor.ps1'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$secretsPath = Join-Path $repoRoot '.env.pg3'
if (-not (Test-Path -LiteralPath $secretsPath)) {
    throw 'Railway connection file .env.pg3 is missing.'
}
$arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}" -DatabaseUrlFile "{1}"' -f $scriptPath, $secretsPath
$action = New-ScheduledTaskAction -Execute (Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe') -Argument $arguments
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -Hidden
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Keeps the local API connected to Railway PostgreSQL; local PostgreSQL receives logical replication.' -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Output "Started scheduled task $TaskName."
