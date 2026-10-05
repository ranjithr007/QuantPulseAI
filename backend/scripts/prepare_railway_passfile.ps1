param([string]$Passfile = 'D:\PostgreSQL\quantpulse_railway_pgpass.conf')

$ErrorActionPreference = 'Stop'
if (Test-Path -LiteralPath $Passfile) {
    throw "Railway passfile already exists: $Passfile"
}
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$line = Get-Content -LiteralPath (Join-Path $repoRoot '.env.pg3') |
    Where-Object { $_ -match '^QUANTPULSE_TARGET_DATABASE_URL=' } |
    Select-Object -First 1
if (-not $line) { throw 'QUANTPULSE_TARGET_DATABASE_URL is missing from .env.pg3.' }
$url = [uri]$line.Substring('QUANTPULSE_TARGET_DATABASE_URL='.Length).Trim('"')
$parts = $url.UserInfo.Split(':', 2)
if ($url.Scheme -notin @('postgres', 'postgresql') -or $parts.Count -ne 2 -or -not $parts[1]) {
    throw 'Invalid Railway PostgreSQL URL.'
}
$user = [uri]::UnescapeDataString($parts[0])
$password = [uri]::UnescapeDataString($parts[1]).Replace('\', '\\').Replace(':', '\:')
$database = $url.AbsolutePath.TrimStart('/')
$record = '{0}:{1}:{2}:{3}:{4}' -f $url.Host, $url.Port, $database, $user, $password
[System.IO.File]::WriteAllText($Passfile, $record + "`n", [System.Text.Encoding]::ASCII)
$acl = Get-Acl -LiteralPath 'D:\PostgreSQL\quantpulse_mirror_password.txt'
Set-Acl -LiteralPath $Passfile -AclObject $acl
Write-Output "Railway replication credential is stored in $Passfile with the mirror credential ACL."
