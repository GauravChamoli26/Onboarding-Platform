# ============================================================================
# p1u4-layout.ps1 - place Phase 1 Unit 4 files (approval engine)
# ----------------------------------------------------------------------------
# USAGE - from inside backend\:
#     Unblock-File .\p1u4-layout.ps1
#     .\p1u4-layout.ps1
#
# Safe to re-run.
# ============================================================================

$ErrorActionPreference = "Continue"

Write-Host ""
Write-Host "=== Phase 1 Unit 4: approval engine ===" -ForegroundColor Cyan
Write-Host ""

# --- Strays -----------------------------------------------------------------
# A conftest.py in the project root is auto-loaded alongside tests\conftest.py
# and hijacks the whole run. Also catches names that shadow the standard library.
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

# --- Directories ------------------------------------------------------------
Write-Host "[2/4] Creating directories" -ForegroundColor White
if (-not (Test-Path "src\platform_core\approvals")) {
    New-Item -ItemType Directory -Path "src\platform_core\approvals" -Force | Out-Null
    Write-Host "      + src\platform_core\approvals" -ForegroundColor Gray
}

# --- Move files -------------------------------------------------------------
Write-Host "[3/4] Moving files" -ForegroundColor White

$fileMap = @{
    # Approval engine
    "business_days.py"            = @{ Dir = "src\platform_core\approvals"; As = "business_days.py" }
    "engine.py"                   = @{ Dir = "src\platform_core\approvals"; As = "engine.py" }
    "escalation.py"               = @{ Dir = "src\platform_core\approvals"; As = "escalation.py" }
    "approvals_init.py"           = @{ Dir = "src\platform_core\approvals"; As = "__init__.py" }
    # Models
    "approval.py"                 = @{ Dir = "src\platform_core\models";    As = "approval.py" }
    "delegation.py"               = @{ Dir = "src\platform_core\models";    As = "delegation.py" }
    "sla_policy.py"               = @{ Dir = "src\platform_core\models";    As = "sla_policy.py" }
    "models_init.py"              = @{ Dir = "src\platform_core\models";    As = "__init__.py" }
    # Migration
    "0005_approval_engine.py"     = @{ Dir = "alembic\versions";            As = "0005_approval_engine.py" }
    # Tests
    "test_business_days.py"       = @{ Dir = "tests";                       As = "test_business_days.py" }
    "test_approvals.py"           = @{ Dir = "tests";                       As = "test_approvals.py" }
    "conftest_tests.py"           = @{ Dir = "tests";                       As = "conftest.py" }
    "test_tenant_isolation.py"    = @{ Dir = "tests";                       As = "test_tenant_isolation.py" }
    "test_migrations.py"          = @{ Dir = "tests";                       As = "test_migrations.py" }
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

# --- Verify -----------------------------------------------------------------
Write-Host "[4/4] Verifying" -ForegroundColor White

$required = @(
    "src\platform_core\approvals\business_days.py",
    "src\platform_core\approvals\engine.py",
    "src\platform_core\approvals\escalation.py",
    "src\platform_core\approvals\__init__.py",
    "src\platform_core\models\approval.py",
    "src\platform_core\models\delegation.py",
    "src\platform_core\models\sla_policy.py",
    "src\platform_core\models\__init__.py",
    "alembic\versions\0005_approval_engine.py",
    "tests\conftest.py",
    "tests\test_business_days.py",
    "tests\test_approvals.py",
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
    Write-Host "      ! conftest.py in project root will hijack the test run" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Phase 1 Unit 4 in place. Next:" -ForegroundColor Cyan
Write-Host "  .\ci-prep.ps1"
Write-Host ""
Write-Host "Expect around 100 tests: 78 existing, plus 22 business-day and" -ForegroundColor Gray
Write-Host "16 approval engine." -ForegroundColor Gray
Write-Host ""
