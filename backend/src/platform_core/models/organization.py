"""
Organization — the tenant entity.

WHAT THIS IS
    One row per hiring organisation. Every other entity in the system points at
    one of these through `organization_id`, and every row-level security policy
    compares against it.

WHY IT INHERITS Base AND NOT TenantModel
    Organization *is* the tenant. Giving it an `organization_id` pointing at
    itself would be circular, and scoping the tenant table by tenant creates a
    chicken-and-egg problem: you cannot look up which organisation you are
    without already knowing.

    Consequently this table carries NO RLS policy. Access is controlled at the
    application layer, and reads go through `get_system_session()`. See
    migration 0001 for the same note on the database side.

SPEC REFERENCE
    Build Spec V3.3 §A1. Only the columns Phase 0 and 2 need are here; the CTC
    rule set, kit profile, retention and document-ordering columns arrive with
    the phases that use them.
"""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from platform_core.db.base import Base


class Organization(Base):
    """A tenant. One row per hiring organisation."""

    __tablename__ = "organizations"

    # Display name, shown in the UI and on internal reports.
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Registered legal name — differs from `name` more often than you would
    # expect, and it is the one that appears on offer letters (Spec §Module 7).
    legal_entity_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Drives business-day SLA calculation (Spec §4.4). A naive calendar-day
    # implementation breaches SLAs across Indian festival clusters, so every
    # deadline computation resolves against this.
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default="Asia/Kolkata")

    def __repr__(self) -> str:
        return f"<Organization {self.name!r} id={self.id}>"
