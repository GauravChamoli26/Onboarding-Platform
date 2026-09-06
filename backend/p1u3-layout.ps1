# ============================================================================
# p1u3-layout.ps1 — place Phase 1 Unit 3 files (audit log)
# ----------------------------------------------------------------------------
# USAGE — from inside backend\:
#     Unblock-File .\p1u3-layout.ps1
#     .\p1u3-layout.ps1
# ============================================================================

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "=== Phase 1 Unit 3: audit log ===" -ForegroundColor Cyan
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
if (-not (Test-Path "src\platform_core\audit")) {
    New-Item -ItemType Directory -Path "src\platform_core\audit" -Force | Out-Null
    Write-Host "      + src\platform_core\audit" -ForegroundColor Gray
}

Write-Host "[3/4] Moving files" -ForegroundColor White
$fileMap = @{
    "hashing.py"                 = @{ Dir = "src\platform_core\audit";  As = "hashing.py" }
    "writer.py"                  = @{ Dir = "src\platform_core\audit";  As = "writer.py" }
    "verification.py"            = @{ Dir = "src\platform_core\audit";  As = "verification.py" }
    "audit_entry.py"             = @{ Dir = "src\platform_core\models"; As = "audit_entry.py" }
    "models_init.py"             = @{ Dir = "src\platform_core\models"; As = "__init__.py" }
    "0004_audit_log.py"          = @{ Dir = "alembic\versions";         As = "0004_audit_log.py" }
    "test_audit.py"              = @{ Dir = "tests";                    As = "test_audit.py" }
    "conftest_tests.py"          = @{ Dir = "tests";                    As = "conftest.py" }
    "test_tenant_isolation.py"   = @{ Dir = "tests";                    As = "test_tenant_isolation.py" }
    "test_migrations.py"         = @{ Dir = "tests";                    As = "test_migrations.py" }
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

@'
"""
Audit log - append-only, hash-chained (ADR-016).

    hashing.py       canonical hashing for the chain
    writer.py        append_audit_entry, and the AuditConsumer
    verification.py  chain verification and the nightly job entry point

Immutability is enforced three ways: no UPDATE or DELETE grant for the
application role, a database trigger that refuses both from anyone, and the hash
chain that makes any alteration detectable. The first two prevent; the third
detects what prevention could not.
"""

from platform_core.audit.hashing import compute_entry_hash
from platform_core.audit.verification import (
    VerificationResult,
    verify_all_chains,
    verify_chain,
)
from platform_core.audit.writer import AuditConsumer, append_audit_entry

__all__ = [
    "AuditConsumer",
    "VerificationResult",
    "append_audit_entry",
    "compute_entry_hash",
    "verify_all_chains",
    "verify_chain",
]
'@ | Set-Content -Path "src\platform_core\audit\__init__.py" -Encoding UTF8
Write-Host "      + src\platform_core\audit\__init__.py" -ForegroundColor Gray

Write-Host "[4/4] Verifying" -ForegroundColor White
$required = @(
    "src\platform_core\audit\hashing.py",
    "src\platform_core\audit\writer.py",
    "src\platform_core\audit\verification.py",
    "src\platform_core\audit\__init__.py",
    "src\platform_core\models\audit_entry.py",
    "src\platform_core\models\__init__.py",
    "alembic\versions\0004_audit_log.py",
    "tests\conftest.py",
    "tests\test_audit.py",
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
Write-Host "Phase 1 Unit 3 in place. Next:" -ForegroundColor Cyan
Write-Host "  pytest -v"
Write-Host ""
Write-Host "Expect 78 tests: 65 existing, plus 13 audit." -ForegroundColor Gray
Write-Host ""
