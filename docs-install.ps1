# ============================================================================
# docs-install.ps1 - place the documentation set into the repository
# ----------------------------------------------------------------------------
# Downloaded files arrive with only their filename, so ADR files land flat.
# This creates docs\ and docs\04-adr\ and sorts everything into place.
#
# WHERE TO RUN
#   From the PROJECT folder - the one containing backend\ and .github\.
#
#       cd "C:\Users\chamo\Desktop\Candidate Onboarding Platform"
#       Unblock-File .\docs-install.ps1
#       .\docs-install.ps1
#
# Safe to re-run.
# ============================================================================

$ErrorActionPreference = "Continue"

Write-Host ""
Write-Host "=== Documentation install ===" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path "backend")) {
    Write-Host "No backend\ directory here." -ForegroundColor Red
    Write-Host "Run this from the project folder, not from inside backend\." -ForegroundColor Red
    exit 1
}

# --- Directories ------------------------------------------------------------
Write-Host "[1/3] Creating directories" -ForegroundColor White
foreach ($dir in @("docs", "docs\04-adr")) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        Write-Host "      + $dir" -ForegroundColor Gray
    }
}

# --- Sort files -------------------------------------------------------------
# ADRs are the numbered 3-digit files plus README and TEMPLATE; everything else
# numbered NN- is a top-level document.
Write-Host "[2/3] Sorting files" -ForegroundColor White

$moved = 0
Get-ChildItem -File -Filter "*.md" | ForEach-Object {
    $name = $_.Name
    $target = $null

    if ($name -match '^\d{3}-') {
        $target = "docs\04-adr\$name"            # 001-..., 016-...
    }
    elseif ($name -in @("TEMPLATE.md")) {
        $target = "docs\04-adr\$name"
    }
    elseif ($name -match '^\d{2}-') {
        $target = "docs\$name"                   # 00-..., 06-...
    }
    elseif ($name -eq "adr-README.md") {
        $target = "docs\04-adr\README.md"        # renamed to avoid a collision
    }

    if ($target) {
        Move-Item -Path $_.FullName -Destination $target -Force
        Write-Host "      > $name -> $target" -ForegroundColor Green
        $script:moved++
    }
}
Write-Host "      $moved file(s) placed" -ForegroundColor Gray

# --- Verify -----------------------------------------------------------------
Write-Host "[3/3] Verifying" -ForegroundColor White

$expectedTop = @(
    "docs\00-documentation-index.md",
    "docs\01-decision-log.md",
    "docs\02-build-spec-v3.3.md",
    "docs\03-solution-design-v3.0.md",
    "docs\06-stack-and-roadmap.md"
)
$missing = $expectedTop | Where-Object { -not (Test-Path $_) }
if ($missing.Count -gt 0) {
    Write-Host "      Missing:" -ForegroundColor Red
    $missing | ForEach-Object { Write-Host "        $_" -ForegroundColor Red }
    exit 1
}

$adrCount = (Get-ChildItem "docs\04-adr" -Filter "0*.md" | Measure-Object).Count
Write-Host "      ok  5 top-level documents" -ForegroundColor Green
Write-Host "      ok  $adrCount ADRs (expected 16)" -ForegroundColor Green
if ($adrCount -ne 16) {
    Write-Host "      ! ADR count differs - check for files still in the project root" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Documentation in place. Next:" -ForegroundColor Cyan
Write-Host "  git add -A"
Write-Host "  git commit -m `"Add documentation set: spec V3.3, SDD 3.0, ADRs, decision log`""
Write-Host "  git push"
Write-Host ""
