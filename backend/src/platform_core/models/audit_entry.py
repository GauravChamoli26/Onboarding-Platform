"""
AuditEntry — one immutable record of something that happened.

WHAT THIS IS FOR
    The spec requires that every status change, feedback entry, approval,
    decision, note, consent action and merge is "logged immutably and
    exportably", and that views of unmasked PII emit SensitiveDataAccessed.

    This table is the evidence base for a discrimination challenge, a DPDP
    inquiry, or an internal investigation into PII misuse. In all three, the
    person with the strongest motive to alter it may be an insider with database
    access — which is why "immutable" here is a mechanism rather than an
    adjective (ADR-016).

THREE LAYERS OF IMMUTABILITY
    1. The application role holds no UPDATE or DELETE grant on this table.
    2. A BEFORE UPDATE OR DELETE trigger raises, which stops even the owner.
    3. Each entry hashes its own content together with the previous entry's
       hash, so altering any entry breaks every hash after it — detectably.

    The first two prevent; the third detects. Both matter: prevention can be
    undone by someone with enough privilege, and detection is what remains.

THE CHAIN IS PER ORGANISATION
    A global chain would be unverifiable by any single tenant, since row-level
    security means they cannot see the entries in between. Per-organisation
    chains are independently verifiable by the tenant they belong to.

NEVER PURGED
    This table sits outside the retention clocks entirely. It carries no
    free-text PII by construction — identifiers, actors and state transitions
    only — so there is nothing in it for a purge to remove.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, String, Text
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from platform_core.db.base import TenantModel

# The previous_hash of the first entry in an organisation's chain. A fixed
# value rather than NULL so that every entry hashes the same way, with no
# special case for the first one.
GENESIS_HASH = "0" * 64


class AuditEntry(TenantModel):
    """One append-only audit record."""

    __tablename__ = "audit_entries"

    # ------------------------------------------------------------------
    # Chain position
    # ------------------------------------------------------------------
    # Sequential within an organisation, starting at 1. Assigned by the writer
    # under an advisory lock rather than by a database sequence, because the
    # chain requires no gaps: a gap is indistinguishable from a deleted entry,
    # and a sequence leaves gaps whenever a transaction rolls back.
    chain_position: Mapped[int] = mapped_column(BigInteger, nullable=False)

    previous_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # ------------------------------------------------------------------
    # Who
    # ------------------------------------------------------------------
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # Null when the actor is the system. Attributing a scheduled job to a user
    # would make the audit trail lie, which defeats the purpose of having one.
    actor_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # The role in effect at the time. Denormalised deliberately: roles change,
    # and an audit entry must record what was true when it was written, not what
    # is true when it is read.
    actor_role: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # ------------------------------------------------------------------
    # What
    # ------------------------------------------------------------------
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)

    # State transition. Identifiers and status values only — never document
    # contents, never an Aadhaar number. See the module docstring.
    before_state: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after_state: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # ------------------------------------------------------------------
    # Context
    # ------------------------------------------------------------------
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # The domain event that produced this entry, where there was one. Null for
    # direct audit writes such as a PII unmask, which is not itself an event.
    event_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Set by the application, not by the database. The value is part of the
    # hashed content, so it must be known before the hash is computed — a
    # server-side now() would be assigned after.
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<AuditEntry #{self.chain_position} {self.action_type} "
            f"{self.entity_type}:{self.entity_id}>"
        )
