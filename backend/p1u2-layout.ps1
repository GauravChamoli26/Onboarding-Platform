# ============================================================================
# p1u2-layout.ps1 — place Phase 1 Unit 2 files (event infrastructure)
# ----------------------------------------------------------------------------
# USAGE — from inside backend\:
#     Unblock-File .\p1u2-layout.ps1
#     .\p1u2-layout.ps1
# ============================================================================

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "=== Phase 1 Unit 2: event infrastructure ===" -ForegroundColor Cyan
Write-Host ""

# --- Stray check ------------------------------------------------------------
# A conftest.py in the project root is auto-loaded alongside tests\conftest.py
# and hijacks the whole run. Also catches stdlib-shadowing names.
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
if (-not (Test-Path "src\platform_core\events")) {
    New-Item -ItemType Directory -Path "src\platform_core\events" -Force | Out-Null
    Write-Host "      + src\platform_core\events" -ForegroundColor Gray
}

# --- Move files -------------------------------------------------------------
Write-Host "[3/4] Moving files" -ForegroundColor White

# Some filenames collide with existing modules elsewhere, so they download
# under a prefixed name and are renamed into place here.
$fileMap = @{
    "catalog.py"                     = @{ Dir = "src\platform_core\events"; As = "catalog.py" }
    "envelope.py"                    = @{ Dir = "src\platform_core\events"; As = "envelope.py" }
    "emitter.py"                     = @{ Dir = "src\platform_core\events"; As = "emitter.py" }
    "consumer.py"                    = @{ Dir = "src\platform_core\events"; As = "consumer.py" }
    "publisher.py"                   = @{ Dir = "src\platform_core\events"; As = "publisher.py" }
    "relay.py"                       = @{ Dir = "src\platform_core\events"; As = "relay.py" }
    "outbox_event.py"                = @{ Dir = "src\platform_core\models"; As = "outbox_event.py" }
    "processed_event.py"             = @{ Dir = "src\platform_core\models"; As = "processed_event.py" }
    "models_init.py"                 = @{ Dir = "src\platform_core\models"; As = "__init__.py" }
    "0003_event_infrastructure.py"   = @{ Dir = "alembic\versions";         As = "0003_event_infrastructure.py" }
    "test_events.py"                 = @{ Dir = "tests";                    As = "test_events.py" }
    "conftest_tests.py"              = @{ Dir = "tests";                    As = "conftest.py" }
    "test_tenant_isolation.py"       = @{ Dir = "tests";                    As = "test_tenant_isolation.py" }
    "test_migrations.py"             = @{ Dir = "tests";                    As = "test_migrations.py" }
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

# --- Package marker ---------------------------------------------------------
@'
"""
Event infrastructure.

    catalog.py    every event type, from Build Spec V3.3
    envelope.py   the envelope every event takes on the bus
    emitter.py    emit_event - writes to the outbox in the caller's transaction
    consumer.py   consumer base class and registry
    publisher.py  publisher interface, in-process and null implementations
    relay.py      moves pending outbox rows to the publisher

The design in one line: events are written with the state change they describe,
and delivered separately. See models/outbox_event.py for why.
"""

from platform_core.events.catalog import ActorType, EventType
from platform_core.events.consumer import ConsumerRegistry, EventConsumer, registry
from platform_core.events.emitter import emit_event
from platform_core.events.envelope import EventEnvelope
from platform_core.events.publisher import (
    EventPublisher,
    InProcessPublisher,
    NullPublisher,
)
from platform_core.events.relay import relay_all_organizations, relay_organization

__all__ = [
    "ActorType",
    "ConsumerRegistry",
    "EventConsumer",
    "EventEnvelope",
    "EventPublisher",
    "EventType",
    "InProcessPublisher",
    "NullPublisher",
    "emit_event",
    "registry",
    "relay_all_organizations",
    "relay_organization",
]
'@ | Set-Content -Path "src\platform_core\events\__init__.py" -Encoding UTF8
Write-Host "      + src\platform_core\events\__init__.py" -ForegroundColor Gray

# --- Verify -----------------------------------------------------------------
Write-Host "[4/4] Verifying" -ForegroundColor White
$required = @(
    "src\platform_core\events\catalog.py",
    "src\platform_core\events\envelope.py",
    "src\platform_core\events\emitter.py",
    "src\platform_core\events\consumer.py",
    "src\platform_core\events\publisher.py",
    "src\platform_core\events\relay.py",
    "src\platform_core\events\__init__.py",
    "src\platform_core\models\outbox_event.py",
    "src\platform_core\models\processed_event.py",
    "src\platform_core\models\__init__.py",
    "alembic\versions\0003_event_infrastructure.py",
    "tests\conftest.py",
    "tests\test_events.py",
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
Write-Host "Phase 1 Unit 2 in place. Next:" -ForegroundColor Cyan
Write-Host "  pytest -v"
Write-Host ""
Write-Host "Expect 66 tests: 51 existing, plus 15 event infrastructure." -ForegroundColor Gray
Write-Host ""
