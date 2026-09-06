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
