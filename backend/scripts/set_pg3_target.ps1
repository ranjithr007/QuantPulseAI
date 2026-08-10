$ErrorActionPreference = "Stop"

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$targetPath = Join-Path $repositoryRoot ".env.pg3"
$secureValue = Read-Host "Paste the PostgreSQL target URL (input is masked)" -AsSecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureValue)

try {
    $value = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer).Trim()
    if (-not $value.StartsWith("postgresql://") -and
        -not $value.StartsWith("postgres://") -and
        -not $value.StartsWith("postgresql+psycopg://")) {
        throw "The target must be a PostgreSQL connection URL."
    }
    if ($value -match "ACTUAL_|USER:PASSWORD|HOST:PORT") {
        throw "The target URL still contains placeholder values."
    }
    if ($value -match "\.railway\.internal(?=[:/])") {
        throw "Use DATABASE_PUBLIC_URL for migration from this computer; DATABASE_URL is Railway-private."
    }
    $content = "QUANTPULSE_TARGET_DATABASE_URL=$value"
    [IO.File]::WriteAllText($targetPath, $content, [Text.UTF8Encoding]::new($false))
    Write-Host "PG3 target credential file saved." -ForegroundColor Green
}
finally {
    if ($pointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
    $value = $null
    $content = $null
    $secureValue.Dispose()
}
