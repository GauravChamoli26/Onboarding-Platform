# ============================================================================
# p1u1-layout.ps1 — place Phase 1 Unit 1 files (identity and access)
# ----------------------------------------------------------------------------
# Downloaded files arrive with only their filename. This puts them where they
# belong, and checks for strays that would break the test run. Safe to re-run.
#
# USAGE — from inside backend\:
#     Unblock-File .\p1u1-layout.ps1
#     .\p1u1-layout.ps1
# ============================================================================

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "=== Phase 1 Unit 1: identity and access ===" -ForegroundColor Cyan
Write-Host ""

# ---------------------------------------------------------------------------
# STEP 1 — Stray file check
# ---------------------------------------------------------------------------
# A conftest.py in the project root is auto-loaded by pytest alongside the one
# in tests\, so a stray copy there hijacks the entire test run. This bit us
# once already; checking is cheaper than diagnosing it again.
Write-Host "[1/4] Checking for stray files" -ForegroundColor White

$strays = @("conftest.py", "types.py", "enum.py", "io.py", "json.py", "logging.py")
$found = $strays | Where-Object { Test-Path $_ }
if ($found.Count -gt 0) {
    Write-Host "      Removing strays from project root:" -ForegroundColor Yellow
    foreach ($stray in $found) {
        Remove-Item $stray -Force
        Write-Host "        - $stray" -ForegroundColor Yellow
    }
}
else {
    Write-Host "      ok  none found" -ForegroundColor Green
}

# ---------------------------------------------------------------------------
# STEP 2 — Move files
# ---------------------------------------------------------------------------
Write-Host "[2/4] Moving files" -ForegroundColor White

$fileMap = @{
    # Models
    "user.py"                       = "src\platform_core\models"
    "role.py"                       = "src\platform_core\models"
    "identity_provider.py"          = "src\platform_core\models"
    # Auth
    "capabilities.py"               = "src\platform_core\auth"
    "principal.py"                  = "src\platform_core\auth"
    "authorization.py"              = "src\platform_core\auth"
    "dev_stub.py"                   = "src\platform_core\auth"
    # API wiring
    "middleware.py"                 = "src\platform_core\api"
    "dependencies.py"               = "src\platform_core\api"
    "errors.py"                     = "src\platform_core\api"
    # Migration
    "0002_identity_and_access.py"   = "alembic\versions"
    # Tests
    "test_authorization.py"         = "tests"
    "conftest_tests.py"             = "tests"   # renamed below
    "test_tenant_isolation.py"      = "tests"
    "test_migrations.py"            = "tests"
}

foreach ($file in $fileMap.Keys | Sort-Object) {
    $dir = $fileMap[$file]
    # conftest_tests.py is downloaded under that name so it cannot be mistaken
    # for a root-level conftest; it becomes tests\conftest.py here.
    $targetName = if ($file -eq "conftest_tests.py") { "conftest.py" } else { $file }
    $target = Join-Path $dir $targetName

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

# ---------------------------------------------------------------------------
# STEP 3 — Model registry
# ---------------------------------------------------------------------------
Write-Host "[3/4] Writing model registry" -ForegroundColor White

@'
"""
Shared-kernel ORM models.

Only entities used by every module live here. Domain entities (Job Posting,
Candidate Profile, Application and so on) belong to their own modules under
src/modules/ from Phase 2 onward.

IMPORTANT: every model must be imported here. Alembic's --autogenerate compares
the live database against Base.metadata, and a model it cannot see looks like a
table that should be dropped.
"""

from platform_core.models.feature_flag import FeatureFlag, FlagKey
from platform_core.models.identity_provider import IdentityProviderConfig, IdpProtocol
from platform_core.models.organization import Organization
from platform_core.models.role import Role, RoleAssignment, ScopeType
from platform_core.models.user import User, UserStatus

__all__ = [
    "FeatureFlag",
    "FlagKey",
    "IdentityProviderConfig",
    "IdpProtocol",
    "Organization",
    "Role",
    "RoleAssignment",
    "ScopeType",
    "User",
    "UserStatus",
]
'@ | Set-Content -Path "src\platform_core\models\__init__.py" -Encoding UTF8
Write-Host "      + src\platform_core\models\__init__.py" -ForegroundColor Gray

# ---------------------------------------------------------------------------
# STEP 4 — Verify
# ---------------------------------------------------------------------------
Write-Host "[4/4] Verifying" -ForegroundColor White

$required = @(
    "src\platform_core\models\user.py",
    "src\platform_core\models\role.py",
    "src\platform_core\models\identity_provider.py",
    "src\platform_core\models\__init__.py",
    "src\platform_core\auth\capabilities.py",
    "src\platform_core\auth\principal.py",
    "src\platform_core\auth\authorization.py",
    "src\platform_core\auth\dev_stub.py",
    "src\platform_core\api\middleware.py",
    "src\platform_core\api\dependencies.py",
    "src\platform_core\api\errors.py",
    "alembic\versions\0002_identity_and_access.py",
    "tests\conftest.py",
    "tests\test_authorization.py",
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

if (Test-Path "conftest.py") {
    Write-Host "      ! WARNING: conftest.py in project root will hijack the test run" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Phase 1 Unit 1 in place. Next:" -ForegroundColor Cyan
Write-Host "  pytest -v"
Write-Host ""
Write-Host "Expect 51 tests: 39 existing, plus 12 authorization." -ForegroundColor Gray
Write-Host ""
