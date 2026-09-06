"""
Observability - logging, correlation, and PII redaction.

    context.py         correlation ID context variable
    redaction.py       PII redaction filter, applied to every log record
    setup_logging.py   root logger configuration

Metrics and tracing arrive with the deployment work in Phase 10. Logging is
here in Phase 0 because redaction has to be in place before anything logs
anything real - retrofitting it means auditing every existing log call.
"""

from platform_core.observability.context import (
    correlation_scope,
    get_correlation_id,
    set_correlation_id,
)
from platform_core.observability.setup_logging import configure_logging

__all__ = [
    "configure_logging",
    "correlation_scope",
    "get_correlation_id",
    "set_correlation_id",
]
