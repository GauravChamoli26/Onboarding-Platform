"""
PII redaction tests.

WHY THESE MATTER MORE THAN THEY LOOK
    Redaction is a control nobody exercises deliberately. It runs on every log
    line and is noticed only when it fails — by which point the PII is already
    in CloudWatch, which is to say already in a place with its own retention
    policy and its own access list.

    These tests are the only thing standing between a well-meaning debug log and
    an Aadhaar number in a log aggregator.

NO CONTAINER NEEDED
    Pure functions and a logging filter. Fast, and runs on every push regardless
    of whether Docker is available.
"""

import logging

from platform_core.observability.redaction import (
    REDACTED,
    RedactionFilter,
    is_sensitive_key,
    redact_text,
    redact_value,
)

# ===========================================================================
# Pattern-based redaction
# ===========================================================================


def test_aadhaar_is_redacted_in_all_common_formats() -> None:
    """
    Aadhaar numbers are redacted whether spaced, hyphenated or bare.

    People write them all three ways, and a pattern that only catches one is
    worse than useless — it creates confidence without coverage.
    """
    for written in ("2345 6789 0123", "2345-6789-0123", "234567890123"):
        result = redact_text(f"Candidate aadhaar is {written}")
        assert "2345" not in result, f"Aadhaar leaked in format: {written}"
        assert "[REDACTED:aadhaar]" in result


def test_pan_is_redacted() -> None:
    """PAN follows a fixed five-letters, four-digits, one-letter shape."""
    result = redact_text("PAN on file: ABCDE1234F")
    assert "ABCDE1234F" not in result
    assert "[REDACTED:pan]" in result


def test_email_is_redacted() -> None:
    """Email addresses identify a candidate directly."""
    result = redact_text("Sending offer to priya.sharma@example.com now")
    assert "priya.sharma@example.com" not in result
    assert "[REDACTED:email]" in result


def test_indian_mobile_is_redacted_with_and_without_country_code() -> None:
    """Indian mobile numbers, +91 prefix optional."""
    for written in ("9876543210", "+91 9876543210", "+919876543210"):
        result = redact_text(f"Calling {written} for screening")
        assert "9876543210" not in result, f"Phone leaked in format: {written}"


def test_redaction_label_survives_so_diagnostics_remain_useful() -> None:
    """
    The redaction marker names what kind of value was removed.

    Knowing an Aadhaar was present at that point is often the entire
    diagnostic value, and the label itself reveals nothing.
    """
    assert redact_text("id 2345 6789 0123") == "id [REDACTED:aadhaar]"


def test_non_pii_text_passes_through_untouched() -> None:
    """Ordinary log messages are not mangled."""
    message = "Application moved from Shortlisted to Screening"
    assert redact_text(message) == message


def test_multiple_pii_values_in_one_message_are_all_redacted() -> None:
    """
    A leak is usually not solitary.

    Debug logs that dump a candidate record contain several sensitive fields at
    once, so redacting only the first would be close to no protection.
    """
    result = redact_text("Candidate: raj@example.com, PAN ABCDE1234F, mobile 9876543210")
    assert "raj@example.com" not in result
    assert "ABCDE1234F" not in result
    assert "9876543210" not in result


# ===========================================================================
# Key-based redaction
# ===========================================================================


def test_sensitive_key_detection_matches_substrings() -> None:
    """
    Field names are matched as substrings, not exactly.

    Nobody names a field exactly "aadhaar". They name it "aadhaar_number",
    "candidate_aadhaar" or "aadhaarRef", and an exact-match denylist would miss
    all three.
    """
    for key in (
        "aadhaar_number",
        "candidate_aadhaar",
        "AadhaarRef",
        "user_password",
        "api_key",
        "bank_account_number",
    ):
        assert is_sensitive_key(key), f"Should be sensitive: {key}"

    for key in ("application_id", "status", "round_number", "created_at"):
        assert not is_sensitive_key(key), f"Should not be sensitive: {key}"


def test_sensitive_values_are_replaced_wholesale() -> None:
    """A field with a sensitive name has its value replaced entirely."""
    assert redact_value("aadhaar_number", "234567890123") == REDACTED
    assert redact_value("password", "hunter2") == REDACTED


def test_redaction_recurses_into_nested_structures() -> None:
    """
    Nested values are no less sensitive for being nested.

    Structured logs routinely carry a nested payload, and a top-level-only
    implementation would miss almost every real case.
    """
    payload = {
        "application_id": "abc-123",
        "candidate": {
            "full_name": "Priya Sharma",
            "documents": {"aadhaar": "234567890123"},
        },
    }
    result = redact_value("payload", payload)
    assert result["application_id"] == "abc-123"  # non-sensitive preserved
    assert result["candidate"]["full_name"] == REDACTED
    assert result["candidate"]["documents"]["aadhaar"] == REDACTED


# ===========================================================================
# The filter in a real logging pipeline
# ===========================================================================


def _capture(record_factory) -> logging.LogRecord:
    """Run a record through RedactionFilter and return the modified record."""
    record = record_factory()
    RedactionFilter().filter(record)
    return record


def test_filter_redacts_the_rendered_message_not_the_template() -> None:
    """
    Redaction happens after argument interpolation.

    This is the case that matters most in practice. `logger.info("PAN: %s", pan)`
    has no PII in `record.msg` at all — it is in `record.args`. Redacting the
    template alone would let every parameterised log line through untouched.
    """
    record = _capture(
        lambda: logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Verifying PAN %s for candidate",
            args=("ABCDE1234F",),
            exc_info=None,
        )
    )
    assert "ABCDE1234F" not in record.getMessage()
    assert "[REDACTED:pan]" in record.getMessage()


def test_filter_redacts_structured_extras() -> None:
    """Fields passed via `extra=` are redacted by key."""

    def build() -> logging.LogRecord:
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Document verified",
            args=(),
            exc_info=None,
        )
        record.aadhaar_number = "234567890123"
        record.application_id = "app-42"
        return record

    record = _capture(build)
    assert record.aadhaar_number == REDACTED
    assert record.application_id == "app-42"


def test_filter_never_drops_records() -> None:
    """
    The filter redacts; it does not suppress.

    Dropping a log line would hide the exact thing somebody is trying to debug,
    and a silently missing log is far harder to diagnose than a redacted one.
    """
    record = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname="",
        lineno=0,
        msg="aadhaar 234567890123",
        args=(),
        exc_info=None,
    )
    assert RedactionFilter().filter(record) is True


def test_filter_survives_a_broken_format_string() -> None:
    """
    A malformed log call must not take down logging itself.

    If interpolation raises, the filter falls back to the raw template rather
    than propagating — losing one message's arguments is recoverable, losing the
    logging pipeline during an incident is not.
    """
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Missing arg %s and %s",
        args=("only-one",),
        exc_info=None,
    )
    assert RedactionFilter().filter(record) is True
