"""
Correlation ID context — ties every log line to the request that caused it.

WHY A CONTEXTVAR RATHER THAN PASSING IT AROUND
    A correlation ID is only useful if it appears on *every* log line, including
    ones written deep inside a service that has no idea an HTTP request exists.
    Threading it through every function signature is the alternative, and nobody
    sustains that past the second sprint.

    Middleware sets it once per request; the logging filter reads it. Code in
    between never mentions it.

SAME PATTERN AS TENANT CONTEXT
    contextvars are async-safe: each task gets its own value. See
    platform_core.tenancy.context for the fuller explanation.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

# "-" rather than None, so log output always has a value in this field and
# downstream log parsers never have to handle a missing key.
_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="-")


def set_correlation_id(correlation_id: str) -> None:
    """Set the correlation ID for the current async context."""
    _correlation_id.set(correlation_id)


def get_correlation_id() -> str:
    """Return the current correlation ID, or '-' if none is set."""
    return _correlation_id.get()


@contextmanager
def correlation_scope(correlation_id: str) -> Iterator[None]:
    """
    Set the correlation ID for a block, restoring the previous value after.

    Used by request middleware and by queue workers, which set the correlation
    ID carried on the event they are processing so that a background action can
    be traced back to the request that triggered it.

    Args:
        correlation_id: the ID to apply for the duration of the block.
    """
    token = _correlation_id.set(correlation_id)
    try:
        yield
    finally:
        _correlation_id.reset(token)
