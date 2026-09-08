"""
Channel adapters - where a notification actually goes.

WHY AN INTERFACE
    Same reason every vendor integration has one (ADR-015). Email is SES or
    SendGrid, SMS is Exotel, Slack is Slack. None of them is contracted or
    configured yet, and the notification service should not have to wait for
    that to be built and tested.

    So the service depends on a protocol, and the real adapters implement it
    when they arrive.

WHAT AN ADAPTER MUST GUARANTEE
    That `send` raises on failure. The service treats any exception as a failed
    delivery and records it. An adapter that swallowed errors would produce
    logs saying messages were sent that never were, which is worse than no logs.
"""

import logging
from dataclasses import dataclass, field
from typing import Protocol

from platform_core.models.notification import NotificationChannel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OutboundMessage:
    """
    A rendered message, ready to send.

    Deliberately NOT stored anywhere. It exists between rendering and dispatch
    and is discarded; the log records which template produced it, not what it
    said. See models/notification.py.
    """

    channel: NotificationChannel
    # An email address, phone number or Slack channel. PII in most cases, which
    # is why this object is transient.
    destination: str
    body: str
    subject: str | None = None
    # SMS only. The adapter passes it to the provider, which validates it
    # against the DLT registry.
    dlt_template_id: str | None = None


class NotificationChannelAdapter(Protocol):
    """Anything that can deliver a rendered message."""

    provider_name: str

    async def send(self, message: OutboundMessage) -> str:
        """
        Deliver one message.

        Args:
            message: the rendered message.

        Returns:
            str: the provider's message identifier, for reconciling a later
            delivery webhook back to the notification log row.

        Raises:
            Exception: on any delivery failure. Never swallow - the service
            records failures and retries, and it can only do that if it is told.
        """
        ...


@dataclass
class RecordingChannelAdapter:
    """
    Records messages instead of sending them.

    The local development and test implementation. Named for what it does
    rather than being a mock, so a test using it is obviously not testing
    delivery.

    Also the honest stand-in until Exotel, SES and Slack are contracted: the
    service, template resolution, DLT gating and logging are all exercised
    exactly as they will be in production, and only the final hop is absent.
    """

    provider_name: str = "recording"
    sent: list[OutboundMessage] = field(default_factory=list)

    async def send(self, message: OutboundMessage) -> str:
        """Record the message and return a synthetic provider ID."""
        self.sent.append(message)
        logger.info(
            "Notification recorded (not sent)",
            extra={
                "channel": message.channel.value,
                # Destination is deliberately absent: it is an email address or
                # phone number, and the redaction filter would strip it anyway.
                "has_subject": message.subject is not None,
            },
        )
        return f"recorded-{len(self.sent)}"

    def clear(self) -> None:
        """Discard recorded messages. For test isolation."""
        self.sent.clear()


@dataclass
class FailingChannelAdapter:
    """Always raises. For exercising the failure path in tests."""

    provider_name: str = "failing"
    error_message: str = "provider unavailable"

    async def send(self, message: OutboundMessage) -> str:
        raise RuntimeError(self.error_message)


class ChannelRegistry:
    """
    Maps each channel to the adapter that serves it.

    A registry rather than import-time wiring, so a test can build one holding
    exactly the adapters it wants to exercise.
    """

    def __init__(self) -> None:
        self._adapters: dict[NotificationChannel, NotificationChannelAdapter] = {}

    def register(self, channel: NotificationChannel, adapter: NotificationChannelAdapter) -> None:
        """Register the adapter serving a channel, replacing any existing one."""
        self._adapters[channel] = adapter

    def get(self, channel: NotificationChannel) -> NotificationChannelAdapter | None:
        """Return the adapter for a channel, or None if none is registered."""
        return self._adapters.get(channel)

    def clear(self) -> None:
        """Remove all adapters. For test isolation."""
        self._adapters.clear()


# Process-wide registry. Adapters register during application startup.
registry = ChannelRegistry()
