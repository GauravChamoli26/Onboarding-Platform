"""
Logging configuration — structured JSON in deployed environments.

WHY JSON
    CloudWatch Logs Insights can query structured fields directly. With plain
    text you are writing regexes against your own log format during an incident,
    which is the worst possible time to do it.

    Locally, JSON is unpleasant to read, so console format is the default there.
    Same fields either way — only the rendering differs.

WHY NO python-json-logger
    It is a small dependency doing a small job, and writing it ourselves keeps
    full control over field names and over where the redaction filter sits in
    the pipeline. Forty lines, no supply chain.

WHAT EVERY LOG LINE CARRIES
    timestamp, level, logger, message, correlation_id — plus whatever structured
    extras the call site passed. The correlation ID arrives automatically from
    the context variable; nobody has to remember to include it.
"""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from platform_core.observability.context import get_correlation_id
from platform_core.observability.redaction import _RESERVED_ATTRS, RedactionFilter


class CorrelationFilter(logging.Filter):
    """Attach the current correlation ID to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Only set if absent, so an explicit correlation_id passed via `extra`
        # wins — useful in workers processing an event that carries its own.
        if not hasattr(record, "correlation_id"):
            record.correlation_id = get_correlation_id()
        return True


class JsonFormatter(logging.Formatter):
    """
    Render a log record as a single-line JSON object.

    One line per record matters: CloudWatch treats a newline as a record
    boundary, so a pretty-printed object becomes several unparseable entries.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            # ISO 8601 with explicit UTC. Timestamps without a zone cause an
            # argument every single time during an incident.
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", "-"),
        }

        # Structured extras passed via logger.info(..., extra={...}).
        for key, value in record.__dict__.items():
            if key not in _RESERVED_ATTRS and key not in payload:
                payload[key] = value

        if record.exc_info:
            # Traceback text only. The exception's own message has already been
            # redacted by RedactionFilter, which runs before the formatter.
            payload["exception"] = self.formatException(record.exc_info)

        # default=str so a UUID or datetime in an extra does not raise
        # mid-logging. A logging call must never be the thing that fails.
        return json.dumps(payload, default=str)


class ConsoleFormatter(logging.Formatter):
    """Human-readable format for local development."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s %(levelname)-8s [%(correlation_id)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )


def configure_logging(level: str = "INFO", json_format: bool = False) -> None:
    """
    Configure the root logger. Call once, at application startup.

    Args:
        level: minimum level to emit — DEBUG, INFO, WARNING, ERROR.
        json_format: True for structured JSON, False for console output.

    FILTER ORDER IS THE IMPORTANT PART
        Both filters are attached to the HANDLER, not to a logger. Filters on a
        logger only see records logged through that logger; filters on a handler
        see everything routed to it, including records from third-party
        libraries that know nothing about our redaction rules.

        Redaction therefore runs before the formatter, which means the formatter
        only ever sees already-redacted content.
    """
    root = logging.getLogger()
    root.setLevel(level.upper())

    # Remove existing handlers so repeated calls — in tests, or under uvicorn's
    # reloader — do not stack up and emit every line multiple times.
    for existing in root.handlers[:]:
        root.removeHandler(existing)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if json_format else ConsoleFormatter())

    handler.addFilter(CorrelationFilter())  # add the ID
    handler.addFilter(RedactionFilter())  # then strip PII from everything

    root.addHandler(handler)

    # Third-party loggers that are noisy at INFO. Raising their level is not
    # about tidiness: SQLAlchemy at INFO logs statement parameters, which for
    # this platform means candidate PII in the application log.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("testcontainers").setLevel(logging.WARNING)
