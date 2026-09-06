"""
OutboxEvent — the transactional outbox row.

THE PROBLEM THIS SOLVES
    The naive implementation writes the state change to the database, then
    publishes to the bus. If the publish fails — network blip, bus outage,
    process killed between the two — the state changed and no event exists.

    That is unrecoverable here. The Candidate 360 Timeline is defined as a
    read-layer over the event stream (Spec §Cross-Cutting 3), so a lost event is
    a permanently wrong candidate history with nothing to reconcile against.

THE PATTERN
    The event row is written in the SAME database transaction as the state
    change. Either both commit or neither does. A separate relay process then
    reads pending rows and publishes them.

    The event is never lost, and never emitted for a state change that rolled
    back. The cost is at-least-once delivery rather than exactly-once — the
    relay can crash after publishing but before marking the row — which is why
    every consumer is idempotent (see ProcessedEvent).

TENANT-SCOPED
    Events belong to an organisation, so this table carries RLS like any other.
    The relay handles that by iterating organisations rather than by bypassing
    the boundary — see events/relay.py.
"""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Identity,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from platform_core.db.base import TenantModel


class OutboxStatus(StrEnum):
    """Publication state of an outbox row."""

    PENDING = "Pending"  # awaiting publication, or awaiting retry
    PUBLISHED = "Published"  # successfully handed to the bus
    FAILED = "Failed"  # retries exhausted — the dead-letter state


class OutboxEvent(TenantModel):
    """One domain event, awaiting or having completed publication."""

    __tablename__ = "outbox_events"

    # ------------------------------------------------------------------
    # Envelope fields
    # ------------------------------------------------------------------
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")

    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)

    application_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True, index=True
    )
    candidate_profile_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    causation_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    # Assigned by the database. See the note on ordering in relay.py — this is a
    # global sequence, so it is monotonic within an organisation as a
    # subsequence, which is what ordering requires.
    #
    # `Identity(always=True)` matches GENERATED ALWAYS AS IDENTITY in the
    # migration, and tells SQLAlchemy the column is server-generated so it is
    # omitted from INSERT and read back afterwards.
    #
    # `autoincrement=True` does NOT do this: SQLAlchemy only honours it on
    # integer primary keys, so on any other column it is silently ignored and
    # the column is sent as NULL — which GENERATED ALWAYS rejects outright.
    #
    # ALWAYS rather than BY DEFAULT is deliberate. Nothing should be able to
    # choose its own sequence number; ordering guarantees depend on the database
    # being the only writer.
    sequence_number: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        nullable=False,
        unique=True,
    )

    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    contains_pii: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    emitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # ------------------------------------------------------------------
    # Publication state
    # ------------------------------------------------------------------
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=OutboxStatus.PENDING.value
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # When the relay may next try. Set on failure using exponential backoff, so
    # a struggling bus is not hammered by a tight retry loop.
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<OutboxEvent {self.event_type} seq={self.sequence_number} status={self.status}>"
