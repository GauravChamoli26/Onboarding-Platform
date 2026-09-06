# ============================================================================
# unit3-layout.ps1 — place Unit 3 files
# ----------------------------------------------------------------------------
# Downloaded files arrive with only their filename. This puts them where they
# belong. Safe to re-run.
#
# USAGE — from inside backend\:
#     Unblock-File .\unit3-layout.ps1
#     .\unit3-layout.ps1
# ============================================================================

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "=== Unit 3 layout ===" -ForegroundColor Cyan
Write-Host ""

Write-Host "[1/4] Creating directories" -ForegroundColor White
foreach ($dir in @("src\platform_core\observability", ".github\workflows")) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        Write-Host "      + $dir" -ForegroundColor Gray
    }
}

# context.py already exists in tenancy\ from Unit 1, and Unit 3 adds a second
# file with the same name under observability\. To avoid a collision on
# download, the observability one is named observability_context.py and
# renamed into place here.
$fileMap = @{
    "observability_context.py"   = @{ Dir = "src\platform_core\observability"; As = "context.py" }
    "redaction.py"               = @{ Dir = "src\platform_core\observability"; As = "redaction.py" }
    "setup_logging.py"           = @{ Dir = "src\platform_core\observability"; As = "setup_logging.py" }
    "settings.py"                = @{ Dir = "src\platform_core\config";        As = "settings.py" }
    "middleware.py"              = @{ Dir = "src\platform_core\api";           As = "middleware.py" }
    "app.py"                     = @{ Dir = "src\platform_core\api";           As = "app.py" }
    "env.py"                     = @{ Dir = "alembic";                         As = "env.py" }
    "test_logging_redaction.py"  = @{ Dir = "tests";                           As = "test_logging_redaction.py" }
    "test_migrations.py"         = @{ Dir = "tests";                           As = "test_migrations.py" }
    "ci.yml"                     = @{ Dir = ".github\workflows";               As = "ci.yml" }
}

Write-Host "[2/4] Moving files" -ForegroundColor White
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

Write-Host "[3/4] Writing package marker" -ForegroundColor White
@'
"""
Observability - logging, correlation, and PII redaction.

    context.py         correlation ID context variable
    redaction.py       PII redaction filter, applied to every log record
    setup_logging.py   root logger configuration

Metrics and tracing arrive with the deployment work in Phase 10. Logging is
here in Phase 0 because redaction has to be in place before anything logs
anything real - retrofitting it means auditing every existing log call.
"""

from platform_core.observability.context import (
    correlation_scope,
    get_correlation_id,
    set_correlation_id,
)
from platform_core.observability.setup_logging import configure_logging

__all__ = [
    "configure_logging",
    "correlation_scope",
    "get_correlation_id",
    "set_correlation_id",
]
'@ | Set-Content -Path "src\platform_core\observability\__init__.py" -Encoding UTF8
Write-Host "      + src\platform_core\observability\__init__.py" -ForegroundColor Gray

Write-Host "[4/4] Verifying" -ForegroundColor White
$required = @(
    "src\platform_core\observability\context.py",
    "src\platform_core\observability\redaction.py",
    "src\platform_core\observability\setup_logging.py",
    "src\platform_core\observability\__init__.py",
    "src\platform_core\config\settings.py",
    "src\platform_core\api\middleware.py",
    "src\platform_core\api\app.py",
    "alembic\env.py",
    "tests\test_logging_redaction.py",
    "tests\test_migrations.py",
    ".github\workflows\ci.yml"
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
Write-Host "Unit 3 in place. Next:" -ForegroundColor Cyan
Write-Host "  pytest -v"
Write-Host ""
Write-Host "Expect 40 tests: 20 from Units 1-2, plus 15 redaction and 5 migration." -ForegroundColor Gray
Write-Host ""
