"""
Notification service.

    channels.py   channel adapter protocol, recording and failing stubs
    service.py    template resolution, rendering, DLT gating, dispatch, logging
    consumer.py   event stream to notification routing

Driven entirely by the event stream (Build Spec V3.3 Cross-Cutting 2). Modules
emit events; nothing sends a notification directly.

Real adapters - SES or SendGrid for email, Exotel for SMS, Slack - arrive with
the deployment work. The service, template resolution, DLT gating and logging
are complete and exercised; only the final hop is stubbed.
"""

from platform_core.notifications.channels import (
    ChannelRegistry,
    FailingChannelAdapter,
    NotificationChannelAdapter,
    OutboundMessage,
    RecordingChannelAdapter,
    registry,
)
from platform_core.notifications.consumer import (
    APPROVAL_RULES,
    NotificationConsumer,
    NotificationRule,
)
from platform_core.notifications.service import (
    NotificationError,
    assert_sendable,
    render,
    resolve_template,
    send_notification,
)

__all__ = [
    "APPROVAL_RULES",
    "ChannelRegistry",
    "FailingChannelAdapter",
    "NotificationChannelAdapter",
    "NotificationConsumer",
    "NotificationError",
    "NotificationRule",
    "OutboundMessage",
    "RecordingChannelAdapter",
    "assert_sendable",
    "registry",
    "render",
    "resolve_template",
    "send_notification",
]
