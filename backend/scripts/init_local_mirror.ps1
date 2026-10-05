param(
    [string]$DataDirectory = 'D:\PostgreSQL\quantpulse_mirror_data',
    [string]$PasswordFile = 'D:\PostgreSQL\quantpulse_mirror_password.txt',
    [string]$LogFile = 'D:\PostgreSQL\quantpulse_mirror.log',
    [string]$PgBin = 'D:\PostgreSQL\bin',
    [int]$Port = 5433
)

$ErrorActionPreference = 'Stop'
if (Test-Path -LiteralPath $DataDirectory) {
    throw "Local mirror data directory already exists: $DataDirectory"
}
if (Test-Path -LiteralPath $PasswordFile) {
    throw "Local mirror password file already exists: $PasswordFile"
}
if ((Get-PSDrive -Name ([System.IO.Path]::GetPathRoot($DataDirectory).TrimEnd('\').TrimEnd(':'))).Free -lt 80GB) {
    throw 'At least 80 GB of free disk space is required for the mirror.'
}

$random = New-Object byte[] 36
[System.Security.Cryptography.RandomNumberGenerator]::Fill($random)
$password = [Convert]::ToBase64String($random)
[System.IO.File]::WriteAllText($PasswordFile, $password, [System.Text.Encoding]::ASCII)
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$acl = Get-Acl -LiteralPath $PasswordFile
$acl.SetAccessRuleProtection($true, $false)
$acl.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new($identity, 'FullControl', 'Allow'))
$acl.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new('NT AUTHORITY\SYSTEM', 'FullControl', 'Allow'))
Set-Acl -LiteralPath $PasswordFile -AclObject $acl

$initdb = Join-Path $PgBin 'initdb.exe'
$pgctl = Join-Path $PgBin 'pg_ctl.exe'
& $initdb --pgdata=$DataDirectory --username=quantpulse_mirror --auth-local=scram-sha-256 --auth-host=scram-sha-256 --pwfile=$PasswordFile --encoding=UTF8
if ($LASTEXITCODE -ne 0) {
    throw "initdb exited with code $LASTEXITCODE. The data directory is preserved for inspection."
}
& $pgctl --pgdata=$DataDirectory --log=$LogFile --options="-p $Port -c listen_addresses=127.0.0.1 -c max_logical_replication_workers=12 -c max_worker_processes=16" start
if ($LASTEXITCODE -ne 0) {
    throw "pg_ctl exited with code $LASTEXITCODE. The data directory is preserved for inspection."
}
$env:PGPASSWORD = $password
try {
    & (Join-Path $PgBin 'psql.exe') -w -h 127.0.0.1 -p $Port -U quantpulse_mirror -d postgres -Atqc 'SELECT 1'
    if ($LASTEXITCODE -ne 0) {
        throw 'The new local mirror PostgreSQL instance did not pass its connection test.'
    }
}
finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
}
Write-Output "Local mirror PostgreSQL is running on 127.0.0.1:$Port. Password is stored in $PasswordFile."
