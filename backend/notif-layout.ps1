# ============================================================================
# notif-layout.ps1 - place the notification service files
# ----------------------------------------------------------------------------
# USAGE - from inside backend\:
#     Unblock-File .\notif-layout.ps1
#     .\notif-layout.ps1
#
# Safe to re-run.
# ============================================================================

$ErrorActionPreference = "Continue"

Write-Host ""
Write-Host "=== Notification service ===" -ForegroundColor Cyan
Write-Host ""

Write-Host "[1/4] Checking for strays" -ForegroundColor White
$strays = @("conftest.py", "types.py", "enum.py", "io.py", "json.py", "logging.py")
$found = $strays | Where-Object { Test-Path $_ }
if ($found.Count -gt 0) {
    foreach ($stray in $found) {
        Remove-Item $stray -Force
        Write-Host "      - removed $stray" -ForegroundColor Yellow
    }
}
else { Write-Host "      ok  none found" -ForegroundColor Green }

Write-Host "[2/4] Creating directories" -ForegroundColor White
if (-not (Test-Path "src\platform_core\notifications")) {
    New-Item -ItemType Directory -Path "src\platform_core\notifications" -Force | Out-Null
    Write-Host "      + src\platform_core\notifications" -ForegroundColor Gray
}

Write-Host "[3/4] Moving files" -ForegroundColor White
$fileMap = @{
    "channels.py"                = @{ Dir = "src\platform_core\notifications"; As = "channels.py" }
    "service.py"                 = @{ Dir = "src\platform_core\notifications"; As = "service.py" }
    "consumer.py"                = @{ Dir = "src\platform_core\notifications"; As = "consumer.py" }
    "notifications_init.py"      = @{ Dir = "src\platform_core\notifications"; As = "__init__.py" }
    "notification.py"            = @{ Dir = "src\platform_core\models";        As = "notification.py" }
    "models_init.py"             = @{ Dir = "src\platform_core\models";        As = "__init__.py" }
    "0006_notifications.py"      = @{ Dir = "alembic\versions";                As = "0006_notifications.py" }
    "test_notifications.py"      = @{ Dir = "tests";                           As = "test_notifications.py" }
    "conftest_tests.py"          = @{ Dir = "tests";                           As = "conftest.py" }
    "test_tenant_isolation.py"   = @{ Dir = "tests";                           As = "test_tenant_isolation.py" }
    "test_migrations.py"         = @{ Dir = "tests";                           As = "test_migrations.py" }
}

foreach ($file in $fileMap.Keys | Sort-Object) {
    $target = Join-Path $fileMap[$file].Dir $fileMap[$file].As
    if (Test-Path $file) {
        Move-Item -Path $file -Destination $target -Force
        Write-Host "      > $file -> $target" -ForegroundColor Green
    }
    elseif (Test-Path $target) {
        Write-Host "      = $target (already in place)" -ForegroundColor DarkGray
    }
    else {
        Write-Host "      ! MISSING: $file" -ForegroundColor Red
    }
}

Write-Host "[4/4] Verifying" -ForegroundColor White
$required = @(
    "src\platform_core\notifications\channels.py",
    "src\platform_core\notifications\service.py",
    "src\platform_core\notifications\consumer.py",
    "src\platform_core\notifications\__init__.py",
    "src\platform_core\models\notification.py",
    "src\platform_core\models\__init__.py",
    "alembic\versions\0006_notifications.py",
    "tests\conftest.py",
    "tests\test_notifications.py",
    "tests\test_tenant_isolation.py",
    "tests\test_migrations.py"
)
$missing = $required | Where-Object { -not (Test-Path $_) }
if ($missing.Count -gt 0) {
    Write-Host ""
    Write-Host "      Missing:" -ForegroundColor Red
    $missing | ForEach-Object { Write-Host "        $_" -ForegroundColor Red }
    exit 1
}
Write-Host "      ok  all $($required.Count) files present" -ForegroundColor Green

Write-Host ""
Write-Host "Notification service in place. Next:" -ForegroundColor Cyan
Write-Host "  .\ci-prep.ps1"
Write-Host ""
Write-Host "Expect around 133 tests: 117 existing, plus 16 notification." -ForegroundColor Gray
Write-Host ""
