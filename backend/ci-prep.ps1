# ============================================================================
# ci-prep.ps1 — get the code green locally before the first push
# ----------------------------------------------------------------------------
# WHY THIS EXISTS
#   The CI pipeline runs formatting, linting, type checking and tests. None of
#   the first three have ever been run over this codebase, so the first push
#   would almost certainly go red on formatting alone — which is a poor
#   introduction to a pipeline and trains people to ignore it.
#
#   This runs the same checks locally, fixing what can be fixed automatically
#   and reporting what cannot.
#
# USAGE — from inside backend\, with the virtual environment active:
#     .\ci-prep.ps1
#
# Run it again after fixing anything it reports, until every step is green.
# ============================================================================

$ErrorActionPreference = "Continue"   # report every step, do not stop at the first

Write-Host ""
Write-Host "=== CI preparation ===" -ForegroundColor Cyan
Write-Host ""

$failures = @()

# ---------------------------------------------------------------------------
# 1. Formatting — auto-fixed
# ---------------------------------------------------------------------------
Write-Host "[1/5] Formatting (ruff format)" -ForegroundColor White
ruff format src tests alembic
if ($LASTEXITCODE -ne 0) { $failures += "ruff format" }
else { Write-Host "      ok" -ForegroundColor Green }

# ---------------------------------------------------------------------------
# 2. Lint — auto-fixed where possible
# ---------------------------------------------------------------------------
Write-Host "[2/5] Lint, auto-fixing (ruff check --fix)" -ForegroundColor White
ruff check --fix src tests alembic
if ($LASTEXITCODE -ne 0) {
    Write-Host "      Some lint findings need manual attention (above)." -ForegroundColor Yellow
    $failures += "ruff check"
}
else { Write-Host "      ok" -ForegroundColor Green }

# ---------------------------------------------------------------------------
# 3. Type check
# ---------------------------------------------------------------------------
Write-Host "[3/5] Type check (mypy)" -ForegroundColor White
mypy
if ($LASTEXITCODE -ne 0) {
    Write-Host "      Type errors above. See the note in pyproject.toml about" -ForegroundColor Yellow
    Write-Host "      tightening mypy incrementally rather than all at once." -ForegroundColor Yellow
    $failures += "mypy"
}
else { Write-Host "      ok" -ForegroundColor Green }

# ---------------------------------------------------------------------------
# 4. Unit tests — fast, no container
# ---------------------------------------------------------------------------
Write-Host "[4/5] Unit tests" -ForegroundColor White
pytest -q -m "not integration"
if ($LASTEXITCODE -ne 0) { $failures += "unit tests" }
else { Write-Host "      ok" -ForegroundColor Green }

# ---------------------------------------------------------------------------
# 5. Integration tests — needs Docker
# ---------------------------------------------------------------------------
Write-Host "[5/5] Integration tests" -ForegroundColor White
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "      SKIPPED: Docker is not running." -ForegroundColor Yellow
    Write-Host "      CI will run these, so start Docker and re-run before pushing." -ForegroundColor Yellow
}
else {
    pytest -q -m integration
    if ($LASTEXITCODE -ne 0) { $failures += "integration tests" }
    else { Write-Host "      ok" -ForegroundColor Green }
}

# ---------------------------------------------------------------------------
Write-Host ""
if ($failures.Count -eq 0) {
    Write-Host "All checks passed. Safe to push." -ForegroundColor Green
}
else {
    Write-Host "Still failing: $($failures -join ', ')" -ForegroundColor Red
    Write-Host "Fix these, then run .\ci-prep.ps1 again." -ForegroundColor Red
}
Write-Host ""
