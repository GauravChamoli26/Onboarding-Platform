"""
PII redaction — applied in the logging pipeline, not by convention.

THE PROBLEM THIS SOLVES
    "Don't log PII" is an instruction, and instructions decay. Somebody debugs a
    parsing failure by logging the parsed resume. Somebody logs the request body
    to diagnose a 422. Somebody logs an exception whose message happens to
    contain the row that failed to insert.

    None of those people are careless — they are debugging, which is exactly
    when the impulse to log everything is strongest. So redaction is a filter
    that every log record passes through, applied whether or not the person who
    wrote the log line thought about it (SDD §6.4, §6.6).

TWO MECHANISMS

    1. Key-based. Structured logging extras whose key matches the denylist have
       their values replaced. Reliable, because it does not depend on guessing
       the shape of a value.

    2. Pattern-based. The rendered message is scanned for Aadhaar, PAN, email
       and Indian phone number patterns. Less precise, and deliberately so — it
       catches values that reached the message through string interpolation,
       which is where accidental leaks actually happen.

ON OVER-REDACTION
    The patterns will occasionally redact something harmless — a twelve-digit
    order reference reads exactly like an Aadhaar number. That is the correct
    direction to err. An over-redacted log costs an engineer five minutes; an
    Aadhaar number in CloudWatch is a reportable incident.
"""

import logging
import re
from typing import Any

REDACTED = "[REDACTED]"

# ---------------------------------------------------------------------------
# Key-based redaction
# ---------------------------------------------------------------------------
# Matched case-insensitively as a SUBSTRING, so "aadhaar" catches
# "aadhaar_number", "candidate_aadhaar" and "aadhaarRef" without enumerating
# every variation someone might invent.
SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        # Identity documents (Spec §Module 6)
        "aadhaar",
        "aadhar",
        "pan",
        "epfo",
        "uan",
        "passport",
        # Credentials and tokens
        "password",
        "secret",
        "token",
        "api_key",
        "apikey",
        "authorization",
        "auth",
        "credential",
        "private_key",
        "session",
        # Direct contact details
        "email",
        "phone",
        "mobile",
        "address",
        "full_name",
        # Financial (Spec §Module 5, §Module 7)
        "salary",
        "ctc",
        "account_number",
        "ifsc",
        "bank",
        # Documents and free text likely to contain any of the above
        "resume",
        "transcript",
        "file_content",
        "note_text",
    }
)

# ---------------------------------------------------------------------------
# Pattern-based redaction
# ---------------------------------------------------------------------------
# Order matters. Aadhaar (12 digits) is matched before phone numbers (10
# digits), or the phone pattern would consume part of an Aadhaar and leave the
# remainder visible.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Aadhaar: 12 digits, commonly written in groups of four.
    ("aadhaar", re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b")),
    # PAN: five letters, four digits, one letter — e.g. ABCDE1234F.
    ("pan", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    # Email address.
    ("email", re.compile(r"\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b")),
    # Indian mobile: optional +91, then 10 digits starting 6-9.
    ("phone", re.compile(r"(?:\+?91[\s-]?)?\b[6-9]\d{9}\b")),
)


def redact_text(text: str) -> str:
    """
    Replace anything matching a PII pattern in a string.

    Args:
        text: the text to scan.

    Returns:
        str: the text with matches replaced by a labelled redaction marker.
             The label is kept — "[REDACTED:aadhaar]" — because knowing *what
             kind* of value was there is often the whole diagnostic value, and
             the label reveals nothing.
    """
    for label, pattern in _PATTERNS:
        text = pattern.sub(f"[REDACTED:{label}]", text)
    return text


def is_sensitive_key(key: str) -> bool:
    """
    Report whether a field name suggests a sensitive value.

    Args:
        key: the field name.

    Returns:
        bool: True if any denylist entry appears in the name.
    """
    lowered = key.lower()
    return any(sensitive in lowered for sensitive in SENSITIVE_KEYS)


def redact_value(key: str, value: Any) -> Any:
    """
    Redact one structured-log field, recursing into containers.

    Args:
        key: the field name, checked against the denylist.
        value: the field value.

    Returns:
        Any: the redacted value. Nested dicts and lists are walked, because a
        sensitive value one level down is no less sensitive.
    """
    if is_sensitive_key(key):
        return REDACTED
    if isinstance(value, dict):
        return {k: redact_value(k, v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        # Keys are unavailable for list items, so only pattern matching applies.
        return [redact_value("", item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


class RedactionFilter(logging.Filter):
    """
    Logging filter that redacts every record passing through a handler.

    Attached to handlers rather than loggers, so that a library logging through
    its own logger is covered too — third-party code has no idea what our PII
    rules are.

    Modifies the record in place. That is what logging filters are permitted to
    do, and it means every downstream handler and formatter sees the redacted
    version rather than each having to redact independently.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """
        Redact the record.

        Args:
            record: the log record, modified in place.

        Returns:
            bool: always True — this filter redacts, it never drops records.
                  Silently dropping a log line would hide the very thing
                  somebody is trying to debug.
        """
        # Render the message with its arguments applied, redact the result, and
        # clear the args. Redacting msg and args separately would miss values
        # that only appear once interpolation has happened.
        try:
            rendered = record.getMessage()
        except Exception:  # noqa: BLE001 - a broken format string must not
            # take down logging itself; fall back to the raw template.
            rendered = str(record.msg)

        record.msg = redact_text(rendered)
        record.args = ()

        # Redact structured extras. Skip logging's own record attributes, which
        # are internal machinery rather than user-supplied fields.
        for key, value in list(record.__dict__.items()):
            if key in _RESERVED_ATTRS:
                continue
            record.__dict__[key] = redact_value(key, value)

        return True


# Attributes the logging module puts on every record. Not user data, and
# rewriting them would corrupt the record.
_RESERVED_ATTRS: frozenset[str] = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "taskName",
    }
)
