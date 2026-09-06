"""
ProcessedEvent — the consumer-side idempotency record.

WHY THIS EXISTS
    Delivery is at-least-once. The relay can publish an event and then crash
    before marking the outbox row, and the next run publishes it again. That is
    an accepted property of the design — exactly-once delivery is not achievable
    across a process boundary, and pretending otherwise produces systems that
    fail in subtler ways.

    So duplicates are expected, and every consumer must be safe against them.
    This table is how: a consumer records the events it has handled, with a
    unique constraint doing the enforcement.

WHY THE MARKER AND THE WORK SHARE A TRANSACTION
    The marker is inserted and the handler runs inside the same transaction. If
    the handler fails, the rollback removes the marker too, so the event is
    retried rather than silently skipped.

    Insert-then-handle in separate transactions would give you the opposite: an
    event marked processed that never was.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from platform_core.db.base import TenantModel


class ProcessedEvent(TenantModel):
    """A record that one consumer has handled one event."""

    __tablename__ = "processed_events"

    # Which consumer. Two consumers must each process the same event, so the
    # uniqueness constraint is on the pair, not on event_id alone.
    consumer_name: Mapped[str] = mapped_column(String(64), nullable=False)

    event_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)

    event_type: Mapped[str] = mapped_column(String(64), nullable=False)

    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<ProcessedEvent {self.consumer_name} event={self.event_id}>"
