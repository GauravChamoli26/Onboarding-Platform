"""
Principal — who is making the current request.

WHAT A PRINCIPAL IS
    The authenticated user, plus their resolved capabilities, for the duration
    of one request. Held in a context variable exactly as the tenant is, and for
    the same reason: threading it through every function signature is the
    alternative, and nobody sustains that.

WHY CAPABILITIES ARE RESOLVED ONCE PER REQUEST
    A capability check is a join across role assignments and roles. Doing it per
    check would mean several round trips for an endpoint that checks two
    permissions. Resolving once and caching on the Principal costs one query.

    The trade-off is that a role change mid-request is not seen until the next
    request. That is correct behaviour, not a limitation — permissions should be
    stable for the duration of an operation, or a half-completed action could
    find itself unauthorised partway through.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from uuid import UUID

from platform_core.auth.capabilities import Capability


@dataclass(frozen=True)
class Principal:
    """
    The authenticated actor for one request.

    Frozen because a principal must not change mid-request. If authorisation
    could be mutated after it was checked, every check becomes advisory.
    """

    user_id: UUID
    organization_id: UUID
    email: str
    capabilities: frozenset[Capability] = field(default_factory=frozenset)

    def has(self, capability: Capability) -> bool:
        """
        Whether this principal holds a capability.

        Args:
            capability: the capability to test.

        Returns:
            bool: True if held.
        """
        return capability in self.capabilities

    def has_any(self, *capabilities: Capability) -> bool:
        """True if the principal holds at least one of the given capabilities."""
        return any(c in self.capabilities for c in capabilities)

    def has_all(self, *capabilities: Capability) -> bool:
        """True if the principal holds every one of the given capabilities."""
        return all(c in self.capabilities for c in capabilities)


class NoPrincipalError(RuntimeError):
    """Raised when an authenticated principal is required but none is set."""


_current_principal: ContextVar[Principal | None] = ContextVar("current_principal", default=None)


def get_principal() -> Principal:
    """
    Return the current principal, raising if the request is unauthenticated.

    Returns:
        Principal: the authenticated actor.

    Raises:
        NoPrincipalError: if no principal is established. Handled in errors.py
            and returned as 401.
    """
    principal = _current_principal.get()
    if principal is None:
        raise NoPrincipalError(
            "No authenticated principal for this request. Endpoints requiring "
            "a capability must be reached through authentication."
        )
    return principal


def get_principal_or_none() -> Principal | None:
    """Return the current principal, or None. For code that tolerates anonymity."""
    return _current_principal.get()


@contextmanager
def principal_scope(principal: Principal | None) -> Iterator[None]:
    """
    Establish the principal for one request, then tear it down.

    Accepts None so that "unauthenticated" is a state we set rather than one we
    fall back into — the same reasoning as `request_tenant_scope`. An
    unauthenticated request inheriting the previous request's principal would be
    privilege escalation, and it would be silent.

    Args:
        principal: the authenticated actor, or None if unauthenticated.
    """
    token = _current_principal.set(principal)
    try:
        yield
    finally:
        _current_principal.reset(token)
