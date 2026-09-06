# ============================================================================
# unit2-layout.ps1 — place Unit 2 files
# ----------------------------------------------------------------------------
# Downloaded files arrive with only their filename, losing the directory they
# belong in. This puts them where they go. Safe to re-run.
#
# USAGE — from inside backend\:
#     .\unit2-layout.ps1
#
# If Windows blocks it:  Unblock-File .\unit2-layout.ps1
# ============================================================================

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "=== Unit 2 layout ===" -ForegroundColor Cyan
Write-Host ""

# --- New directories --------------------------------------------------------
$directories = @(
    "src\platform_core\models",
    "src\platform_core\auth",
    "src\platform_core\api"
)
Write-Host "[1/4] Creating directories" -ForegroundColor White
foreach ($dir in $directories) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        Write-Host "      + $dir" -ForegroundColor Gray
    }
}

# --- File placement ---------------------------------------------------------
# Note: __init__.py files are generated below rather than downloaded, because
# several would otherwise collide on filename.
$fileMap = @{
    "organization.py"       = "src\platform_core\models"
    "feature_flag.py"       = "src\platform_core\models"
    "dev_stub.py"           = "src\platform_core\auth"
    "middleware.py"         = "src\platform_core\api"
    "dependencies.py"       = "src\platform_core\api"
    "errors.py"             = "src\platform_core\api"
    "routes.py"             = "src\platform_core\api"
    "app.py"                = "src\platform_core\api"
    "conftest.py"           = "tests"
    "test_api_tenancy.py"   = "tests"
}

Write-Host "[2/4] Moving files" -ForegroundColor White
$missing = @()
foreach ($file in $fileMap.Keys | Sort-Object) {
    $destination = Join-Path $fileMap[$file] $file
    if (Test-Path $file) {
        Move-Item -Path $file -Destination $destination -Force
        Write-Host "      > $file -> $destination" -ForegroundColor Green
    }
    elseif (Test-Path $destination) {
        Write-Host "      = $destination (already in place)" -ForegroundColor DarkGray
    }
    else {
        $missing += $file
        Write-Host "      ! MISSING: $file" -ForegroundColor Red
    }
}

# --- Package markers --------------------------------------------------------
Write-Host "[3/4] Writing package markers" -ForegroundColor White

$packageDocs = @{
    "src\platform_core\models\__init__.py" = @'
"""
Shared-kernel ORM models.

Only entities used by every module live here - currently the tenant itself and
feature flags. Domain entities belong to their own modules under src/modules/.

IMPORTANT: every model must be imported here. Alembic's --autogenerate compares
the live database against Base.metadata, and a model it cannot see looks like a
table that should be dropped.
"""

from platform_core.models.feature_flag import FeatureFlag, FlagKey
from platform_core.models.organization import Organization

__all__ = ["FeatureFlag", "FlagKey", "Organization"]
'@
    "src\platform_core\auth\__init__.py" = @'
"""
Authentication and authorisation.

Currently contains only the development stub (dev_stub.py), which is temporary
scaffolding to be deleted in Phase 1.

Phase 1 adds: SAML 2.0 and OIDC service provider implementation (ADR-006),
capability-based authorisation middleware, and the candidate portal token
exchange (ADR-010).
"""
'@
    "src\platform_core\api\__init__.py" = @'
"""
HTTP layer.

    app.py           application factory and lifespan
    middleware.py    correlation IDs and tenant resolution
    dependencies.py  session and tenant dependencies for route handlers
    errors.py        exception handlers that never leak internals or PII
    routes.py        health checks and the feature-flag endpoint

Domain routes live with their modules under src/modules/ from Phase 2 onward.
"""
'@
}

foreach ($path in $packageDocs.Keys) {
    $packageDocs[$path] | Set-Content -Path $path -Encoding UTF8
    Write-Host "      + $path" -ForegroundColor Gray
}

# --- Verify -----------------------------------------------------------------
Write-Host "[4/4] Verifying" -ForegroundColor White

$required = @(
    "src\platform_core\models\organization.py",
    "src\platform_core\models\feature_flag.py",
    "src\platform_core\models\__init__.py",
    "src\platform_core\auth\dev_stub.py",
    "src\platform_core\auth\__init__.py",
    "src\platform_core\api\app.py",
    "src\platform_core\api\middleware.py",
    "src\platform_core\api\dependencies.py",
    "src\platform_core\api\errors.py",
    "src\platform_core\api\routes.py",
    "src\platform_core\api\__init__.py",
    "tests\conftest.py",
    "tests\test_api_tenancy.py",
    "pyproject.toml"
)
$stillMissing = $required | Where-Object { -not (Test-Path $_) }

if ($stillMissing.Count -gt 0) {
    Write-Host ""
    Write-Host "      Missing:" -ForegroundColor Red
    $stillMissing | ForEach-Object { Write-Host "        $_" -ForegroundColor Red }
    exit 1
}

Write-Host "      ok  all $($required.Count) files present" -ForegroundColor Green
Write-Host ""
Write-Host "Unit 2 in place. Next:" -ForegroundColor Cyan
Write-Host "  python -m pip install -e `".[dev]`"     # picks up httpx"
Write-Host "  pytest -v -m integration"
Write-Host ""
