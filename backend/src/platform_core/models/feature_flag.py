"""
Feature Flag — per-organisation behaviour switches.

WHAT THIS IS
    One row per flag per organisation. Flags govern behaviour and never cause
    silent data destruction — turning Talent Pool off makes pooled profiles
    non-searchable, it does not delete them (Spec V3.3 §Feature Flags).

WHY THIS IS THE FIRST TENANT-SCOPED TABLE
    It is the simplest genuinely-needed entity in the system, which makes it the
    natural proving ground for the row-level security pattern every later table
    follows.

SPEC REFERENCE
    Build Spec V3.3 §Feature Flags, SDD §A4.
"""

from enum import StrEnum
from uuid import UUID

from sqlalchemy import Boolean, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from platform_core.db.base import TenantModel


class FlagKey(StrEnum):
    """
    Every flag the platform recognises.

    A StrEnum rather than a plain Enum so that members compare equal to their
    string value — which means the same constant works in Python comparisons,
    SQL parameters and JSON responses without conversion.

    Must stay in step with the check constraint in migration 0001. Adding a flag
    means a new migration amending that constraint.
    """

    TALENT_POOL = "TalentPool"
    AI_COPILOT = "AICopilot"
    CONFIGURABLE_PIPELINES = "ConfigurablePipelines"
    INTERNAL_NOTES = "InternalNotes"
    CROSS_ROUND_FEEDBACK_VISIBILITY = "CrossRoundFeedbackVisibility"
    AI_SCREENING = "AIScreening"  # off at launch — voice deferred (D-01)
    BACKGROUND_VERIFICATION = "BackgroundVerification"
    KIT_DISPATCH = "KitDispatch"


class FeatureFlag(TenantModel):
    """A single flag's state for one organisation."""

    __tablename__ = "feature_flags"

    # Stored as text with a database check constraint rather than a native
    # PostgreSQL enum. Adding a value to a PG enum needs a migration and takes
    # locks; a check constraint is cheap to amend, and audit exports stay
    # readable a decade out either way (SDD §0).
    flag_key: Mapped[str] = mapped_column(String(64), nullable=False)

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    # Attribution. Flags gate compliance-relevant behaviour — AI Copilot most
    # obviously — so who flipped one and why is not optional metadata.
    changed_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        state = "on" if self.enabled else "off"
        return f"<FeatureFlag {self.flag_key}={state} org={self.organization_id}>"
