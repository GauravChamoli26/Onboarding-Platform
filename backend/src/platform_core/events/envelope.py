"""
Event envelope — the shape every domain event takes on the bus.

WHY EVERY FIELD IS HERE
    See SDD §2.1. The ones that look optional are not:

    schema_version   Payload shapes change. Consumers must be able to branch on
                     the version rather than break on an unexpected key.
    sequence_number  Gives consumers ordering and gap detection.
    correlation_id   One HR action fans out into notifications, audit entries
                     and timeline rows. Tracing needs the chain.
    causation_id     Which event caused this one, where an event was emitted by
                     a consumer reacting to another.
    contains_pii     Drives redaction in logs, exports and the dead-letter queue.

THE PAYLOAD RULE
    Payloads carry identifiers and state transitions, never PII. A
    `DocumentSubmitted` event carries the document type and record ID — never
    the file, never the Aadhaar number.

    This is not a style preference. It is what keeps the event store outside the
    retention purge path: if events contained personal data, every purge would
    have to rewrite history, and an append-only event log cannot be rewritten.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from platform_core.events.catalog import ActorType, EventType

# Bumped when the envelope itself changes shape — not when a payload does.
# Payload changes are the emitting module's concern.
CURRENT_SCHEMA_VERSION = 1


class EventEnvelope(BaseModel):
    """
    A domain event, ready to publish.

    Immutable: an event describes something that already happened, and something
    that already happened cannot be edited. Pydantic's frozen config enforces
    that rather than leaving it to convention.
    """

    model_config = ConfigDict(frozen=True)

    event_id: UUID
    event_type: EventType
    schema_version: int = CURRENT_SCHEMA_VERSION

    # --- Tenancy and subject ------------------------------------------------
    organization_id: UUID
    entity_type: str = Field(max_length=64)
    entity_id: UUID

    # Denormalised so the Timeline and Talent Pool read-models need no joins.
    # Null on events that concern no specific application or candidate — a
    # feature flag change, for instance.
    application_id: UUID | None = None
    candidate_profile_id: UUID | None = None

    # --- Provenance ---------------------------------------------------------
    actor_type: ActorType
    # Null when actor_type is SYSTEM. A scheduled job has no user behind it, and
    # inventing one would make the audit trail lie.
    actor_id: UUID | None = None

    correlation_id: str
    causation_id: UUID | None = None
    sequence_number: int | None = None  # assigned by the database on insert

    # --- Content ------------------------------------------------------------
    payload: dict[str, Any] = Field(default_factory=dict)
    contains_pii: bool = False

    emitted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """
        Serialise for publication.

        Returns:
            dict: JSON-compatible, with UUIDs and datetimes as strings.
        """
        return self.model_dump(mode="json")
