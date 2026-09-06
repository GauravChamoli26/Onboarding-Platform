# ============================================================================
# git-setup.ps1 - initialise the repository and prepare the first push
# ----------------------------------------------------------------------------
# WHERE TO RUN THIS
#   From the PROJECT folder - the one containing backend\ - not from inside
#   backend\.
#
#       cd "C:\Users\chamo\Desktop\Candidate Onboarding Platform"
#       .\git-setup.ps1
#
# WHY THE REPOSITORY ROOT IS THE PROJECT FOLDER
#   Documentation and code version together. A change to the spec and the code
#   implementing it belong in one commit, which is what makes the change-control
#   process in docs/00 workable rather than aspirational.
#
#   The CI workflow assumes this layout: every job sets
#   working-directory: backend.
#
# SAFE TO RE-RUN. Existing repositories are left alone.
# ============================================================================

# Continue rather than Stop: git writes ordinary progress and advisory
# messages to stderr, and under "Stop" PowerShell treats those as terminating
# errors. Each step below checks its own outcome explicitly instead.
$ErrorActionPreference = "Continue"

Write-Host ""
Write-Host "=== Repository setup ===" -ForegroundColor Cyan
Write-Host ""

# --- Sanity check: are we in the right place? -------------------------------
if (-not (Test-Path "backend")) {
    Write-Host "No backend\ directory here." -ForegroundColor Red
    Write-Host "Run this from the project folder, not from inside backend\." -ForegroundColor Red
    exit 1
}

# --- A nested repository breaks everything downstream -----------------------
# If backend\ contains its own .git, the outer repository records it as an
# embedded repository: a bare pointer with none of the files inside. CI would
# check out an empty backend\ and every job would fail on a missing file.
#
# This is a hard stop rather than a warning, because continuing produces a
# repository that looks fine locally and is broken the moment it is cloned.
if (Test-Path "backend\.git") {
    Write-Host "STOP: backend\ contains its own git repository." -ForegroundColor Red
    Write-Host ""
    Write-Host "The outer repository would record backend\ as an embedded repo -" -ForegroundColor Red
    Write-Host "a pointer with no files. CI would check out an empty directory." -ForegroundColor Red
    Write-Host ""
    Write-Host "Remove it, then run this script again:" -ForegroundColor Yellow
    Write-Host "    Remove-Item -Recurse -Force .\backend\.git" -ForegroundColor White
    Write-Host ""
    Write-Host "That discards the local commits inside backend\. They were never" -ForegroundColor Gray
    Write-Host "pushed and the working tree is unchanged - only the intermediate" -ForegroundColor Gray
    Write-Host "history goes." -ForegroundColor Gray
    Write-Host ""
    exit 1
}

# --- Initialise -------------------------------------------------------------
Write-Host "[1/4] Repository" -ForegroundColor White
if (Test-Path ".git") {
    Write-Host "      = already initialised" -ForegroundColor DarkGray
}
else {
    git init
    # 'main' rather than 'master'. GitHub defaults to main, and a mismatch means
    # the CI workflow's branch filter silently never fires.
    git branch -M main
    Write-Host "      + initialised on branch 'main'" -ForegroundColor Green
}

# --- Root .gitignore --------------------------------------------------------
Write-Host "[2/4] Root .gitignore" -ForegroundColor White
if (Test-Path ".gitignore") {
    Write-Host "      = already present" -ForegroundColor DarkGray
}
elseif (Test-Path "gitignore-root.txt") {
    Move-Item "gitignore-root.txt" ".gitignore"
    Write-Host "      + created from gitignore-root.txt" -ForegroundColor Green
}
else {
    Write-Host "      ! gitignore-root.txt not found - download it first" -ForegroundColor Red
    exit 1
}

# --- What would be committed ------------------------------------------------
Write-Host "[3/4] Reviewing what would be committed" -ForegroundColor White

# `git status --short` rather than `git add --dry-run`: it reports the same
# thing, touches nothing, and writes to stdout so PowerShell does not treat
# git's ordinary progress output as a terminating error.
$status = git status --short
if (-not $status) {
    Write-Host "      Nothing to commit - the working tree is clean." -ForegroundColor DarkGray
}
else {
    $shown = $status | Select-Object -First 30
    $shown | ForEach-Object { Write-Host "      $_" -ForegroundColor DarkGray }
    $total = ($status | Measure-Object).Count
    if ($total -gt 30) {
        Write-Host "      ... and $($total - 30) more" -ForegroundColor DarkGray
    }
}
Write-Host ""

# Anything that looks like a credential must not be committed. A secret in git
# history survives deletion of the file, so this check is the last cheap moment
# to catch it.
$secretish = $status | Where-Object { $_ -match '\.env$|\.pem$|\.key$|\.p12$' }
if ($secretish) {
    Write-Host "      STOP: files that look like secrets are untracked or staged:" -ForegroundColor Red
    $secretish | ForEach-Object { Write-Host "        $_" -ForegroundColor Red }
    Write-Host "      Check .gitignore before committing." -ForegroundColor Red
    exit 1
}
Write-Host "      ok  no secret-looking files" -ForegroundColor Green
Write-Host ""

# --- Next steps -------------------------------------------------------------
Write-Host "[4/4] Next steps" -ForegroundColor White
Write-Host ""
Write-Host "  1. Get the code green locally first:" -ForegroundColor Cyan
Write-Host "       cd backend"
Write-Host "       .\ci-prep.ps1"
Write-Host "       cd .."
Write-Host ""
Write-Host "  2. Commit:" -ForegroundColor Cyan
Write-Host "       git add -A"
Write-Host "       git commit -m `"Phase 0 and Phase 1 units 1-3: platform foundation`""
Write-Host ""
Write-Host "  3. Create an EMPTY repository on GitHub - no README, no .gitignore," -ForegroundColor Cyan
Write-Host "     no licence. Anything pre-created causes a push conflict."
Write-Host ""
Write-Host "  4. Connect and push:" -ForegroundColor Cyan
Write-Host "       git remote add origin https://github.com/<you>/<repo>.git"
Write-Host "       git push -u origin main"
Write-Host ""
Write-Host "  5. Open the Actions tab. The workflow runs automatically." -ForegroundColor Cyan
Write-Host ""
