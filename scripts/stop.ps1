# Dash FIDCs: stop the app and PostgreSQL. Double-click Parar.cmd, or:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\stop.ps1 [-AppOnly]
# Jobs that were running are marked as interrupted the next time the app starts.
param(
    [switch]$AppOnly   # stop the app but leave PostgreSQL running
)
. (Join-Path $PSScriptRoot "common.ps1")

try {
    Assert-FullLanguage
    # Waits for an Iniciar.cmd still running in another window (setup can take minutes).
    Assert-ScriptLock 120
    Stop-App
    if (-not $AppOnly) { Stop-Postgres }
    Write-Host ""
    Write-Host "Dash FIDCs parado." -ForegroundColor Green
    exit 0
} catch {
    Write-Host ""
    Write-Host "ERRO: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
} finally {
    Exit-ScriptLock
}
