# ============================================================================
# bootstrap.ps1 — one-time project layout
# ----------------------------------------------------------------------------
# WHAT THIS DOES
#   Takes a backend/ folder where every file is sitting flat in the root and
#   arranges it into the correct Python package structure. Also cleans up two
#   things that cause real problems, and generates .gitignore.
#
# WHY LAYOUT MATTERS HERE
#   Python searches the current directory first when importing. A file named
#   types.py in the project root is found before the standard library's `types`
#   module. Since `enum` imports `types`, and `uuid` imports `enum`, that single
#   misplaced file breaks the interpreter before any of our code runs. That is
#   the error you saw.
#
# SAFE TO RE-RUN
#   Files already in place are left alone. Nothing is deleted except build
#   artefacts and files explicitly listed as junk.
#
# USAGE
#   Run once from inside backend\:
#       .\bootstrap.ps1
# ============================================================================

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "=== Backend layout bootstrap ===" -ForegroundColor Cyan
Write-Host ""

# ---------------------------------------------------------------------------
# STEP 1 — Directory structure
# ---------------------------------------------------------------------------
# src/       application code, kept out of the root so tests import the
#            installed package rather than accidentally picking up loose files
# alembic/   migrations
# tests/     test suite
# scripts/   database bootstrap SQL
$directories = @(
    "src\platform_core\config",
    "src\platform_core\db",
    "src\platform_core\tenancy",
    "alembic\versions",
    "tests",
    "scripts"
)

Write-Host "[1/5] Creating directories" -ForegroundColor White
foreach ($dir in $directories) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        Write-Host "      + $dir" -ForegroundColor DarkGray
    }
}

# ---------------------------------------------------------------------------
# STEP 2 — Remove junk
# ---------------------------------------------------------------------------
# __pycache__  compiled bytecode from the failed run. Orphaned once types.py
#              moves, but stale caches cause confusing behaviour, so clear it.
# get-pip.py   not part of this project. Python 3.13 bundles pip already, and
#              leaving a 2MB script in the root only invites confusion later.
Write-Host "[2/5] Cleaning up" -ForegroundColor White

if (Test-Path "__pycache__") {
    Remove-Item -Recurse -Force "__pycache__"
    Write-Host "      - __pycache__ (stale bytecode from the shadowing error)" -ForegroundColor Yellow
}
if (Test-Path "get-pip.py") {
    Remove-Item -Force "get-pip.py"
    Write-Host "      - get-pip.py (not part of this project)" -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
# STEP 3 — Move files into their packages
# ---------------------------------------------------------------------------
# Anything not listed here belongs in the project root and is left alone:
# pyproject.toml, alembic.ini, docker-compose.yml, Makefile, make.ps1, .env
$fileMap = @{
    "settings.py"                = "src\platform_core\config"
    "base.py"                    = "src\platform_core\db"
    "session.py"                 = "src\platform_core\db"
    "types.py"                   = "src\platform_core\db"
    "context.py"                 = "src\platform_core\tenancy"
    "env.py"                     = "alembic"
    "0001_tenancy_foundation.py" = "alembic\versions"
    "conftest.py"                = "tests"
    "test_tenant_isolation.py"   = "tests"
    "init-db.sql"                = "scripts"
}

Write-Host "[3/5] Moving files into packages" -ForegroundColor White
$missing = @()
foreach ($file in $fileMap.Keys | Sort-Object) {
    $destination = Join-Path $fileMap[$file] $file

    if (Test-Path $destination) {
        # Already correct. If a stray copy remains in the root it would still
        # shadow imports, so remove it.
        if (Test-Path $file) {
            Remove-Item $file
            Write-Host "      - removed duplicate root copy: $file" -ForegroundColor Yellow
        }
        Write-Host "      = $destination (already in place)" -ForegroundColor DarkGray
    }
    elseif (Test-Path $file) {
        Move-Item -Path $file -Destination $destination
        Write-Host "      > $file -> $destination" -ForegroundColor Green
    }
    else {
        $missing += $destination
        Write-Host "      ! MISSING: $file" -ForegroundColor Red
    }
}

# ---------------------------------------------------------------------------
# STEP 4 — Package markers and .gitignore
# ---------------------------------------------------------------------------
# __init__.py makes a directory an importable Python package. Empty by design,
# except platform_core's which carries the package docstring.
Write-Host "[4/5] Creating package markers and .gitignore" -ForegroundColor White

foreach ($init in @(
    "src\platform_core\config\__init__.py",
    "src\platform_core\db\__init__.py",
    "src\platform_core\tenancy\__init__.py",
    "tests\__init__.py"
)) {
    if (-not (Test-Path $init)) {
        New-Item -ItemType File -Path $init -Force | Out-Null
        Write-Host "      + $init" -ForegroundColor DarkGray
    }
}

$rootInit = "src\platform_core\__init__.py"
if (-not (Test-Path $rootInit)) {
    @'
"""
platform_core - the shared kernel.

Everything in this package is used by every functional module. Nothing here
knows about jobs, candidates, offers or any other domain concept; if it does,
it belongs in src/modules/ instead.

Layout (SDD 3.0):
    config/    application settings, environment-backed
    db/        engine, session handling, base model conventions
    tenancy/   the tenant context that drives row-level security

Phase 1 adds: auth/, events/, audit/, approvals/, notifications/, sla/
"""
'@ | Set-Content -Path $rootInit -Encoding UTF8
    Write-Host "      + $rootInit" -ForegroundColor DarkGray
}

# .gitignore. Two entries are security-relevant rather than housekeeping:
# .env holds real credentials, and a committed .env stays in git history
# forever even after deletion.
if (-not (Test-Path ".gitignore")) {
    @'
# --- Virtual environments ---------------------------------------------------
.venv/
venv/
env/

# --- Secrets (security-relevant: git history survives deletion) -------------
.env
.env.local
*.pem
*.key

# --- Python build artefacts -------------------------------------------------
__pycache__/
*.py[cod]
*.egg-info/
dist/
build/

# --- Tooling caches ---------------------------------------------------------
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage

# --- Editors / OS -----------------------------------------------------------
.vscode/
.idea/
.DS_Store
Thumbs.db
'@ | Set-Content -Path ".gitignore" -Encoding UTF8
    Write-Host "      + .gitignore" -ForegroundColor DarkGray
}

# ---------------------------------------------------------------------------
# STEP 5 — Verify
# ---------------------------------------------------------------------------
Write-Host "[5/5] Verifying" -ForegroundColor White

# The check that matters most: nothing in the root may share a name with a
# standard library module. types.py caused the original failure; the same trap
# exists for these others.
$shadowRisks = @("types.py", "enum.py", "io.py", "json.py", "string.py",
                 "uuid.py", "time.py", "os.py", "logging.py", "select.py",
                 "email.py", "code.py", "test.py", "abc.py")
$shadowing = $shadowRisks | Where-Object { Test-Path $_ }

if ($shadowing.Count -gt 0) {
    Write-Host ""
    Write-Host "      FAILED: these shadow standard library modules:" -ForegroundColor Red
    $shadowing | ForEach-Object { Write-Host "        $_" -ForegroundColor Red }
    exit 1
}
Write-Host "      ok  no standard library shadowing" -ForegroundColor Green

$required = @(
    "pyproject.toml", "alembic.ini", "docker-compose.yml",
    "src\platform_core\__init__.py",
    "src\platform_core\config\settings.py",
    "src\platform_core\db\base.py",
    "src\platform_core\db\session.py",
    "src\platform_core\db\types.py",
    "src\platform_core\tenancy\context.py",
    "alembic\env.py",
    "alembic\versions\0001_tenancy_foundation.py",
    "tests\conftest.py",
    "tests\test_tenant_isolation.py",
    "scripts\init-db.sql"
)
$stillMissing = $required | Where-Object { -not (Test-Path $_) }

if ($stillMissing.Count -gt 0) {
    Write-Host ""
    Write-Host "      Missing files:" -ForegroundColor Red
    $stillMissing | ForEach-Object { Write-Host "        $_" -ForegroundColor Red }
    Write-Host ""
    Write-Host "      Download these and re-run bootstrap.ps1" -ForegroundColor Yellow
    exit 1
}
Write-Host "      ok  all $($required.Count) required files present" -ForegroundColor Green

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "Layout complete." -ForegroundColor Cyan
Write-Host ""
Write-Host "Next, run these three commands:" -ForegroundColor White
Write-Host "  py -m venv .venv"
Write-Host "  .\.venv\Scripts\Activate.ps1"
Write-Host "  python -m pip install -e `".[dev]`""
Write-Host ""
Write-Host "Your prompt should show (.venv) after the second command." -ForegroundColor Gray
Write-Host ""
