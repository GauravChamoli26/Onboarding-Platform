"""
Canonical hashing for the audit chain.

WHY CANONICALISATION MATTERS MORE THAN THE HASH ALGORITHM
    Verification recomputes each entry's hash and compares it to the stored one.
    If serialisation is not byte-for-byte deterministic, an untampered chain
    fails verification — and a verifier that cries wolf gets switched off, which
    leaves you with no verification at all.

    Two things make it deterministic here: keys are sorted, and separators are
    fixed so no incidental whitespace creeps in. Both are explicit rather than
    relying on defaults, because json.dumps defaults have changed before.

WHAT GOES INTO THE HASH
    Every content field of the entry, plus the previous entry's hash. Not the
    entry's own hash, obviously, and not its database id — the id is assigned by
    the application and carries no meaning the chain depends on.
"""

import hashlib
import json
from datetime import datetime
from typing import Any
from uuid import UUID


def _canonical(value: Any) -> Any:
    """
    Convert a value to a stable, JSON-serialisable form.

    UUIDs and datetimes both have several plausible string forms; pinning them
    here means the same entry always hashes identically, including across
    Python versions.
    """
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        # isoformat with an explicit offset. A naive datetime would serialise
        # differently depending on the writer's timezone.
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    return value


def compute_entry_hash(
    *,
    organization_id: UUID,
    chain_position: int,
    previous_hash: str,
    actor_type: str,
    actor_id: UUID | None,
    actor_role: str | None,
    action_type: str,
    entity_type: str,
    entity_id: UUID,
    before_state: dict[str, Any] | None,
    after_state: dict[str, Any] | None,
    correlation_id: str,
    event_id: UUID | None,
    occurred_at: datetime,
) -> str:
    """
    Compute the SHA-256 hash of one audit entry.

    Args:
        organization_id: the tenant. Included so an entry cannot be moved
            between chains without detection.
        chain_position: position in this organisation's chain.
        previous_hash: the preceding entry's hash — what makes it a chain rather
            than a set of independent hashes.
        actor_type: User, System, Candidate or Vendor.
        actor_id: the acting user, or None for system actions.
        actor_role: the role in effect at the time.
        action_type: what happened.
        entity_type: what it happened to.
        entity_id: which one.
        before_state: prior state, where applicable.
        after_state: resulting state, where applicable.
        correlation_id: ties this to the request that caused it.
        event_id: the domain event that produced it, where there was one.
        occurred_at: when. Application-assigned, since it is hashed.

    Returns:
        str: 64-character lowercase hex digest.

    Any change to the field set here invalidates every existing chain, so this
    signature is effectively frozen once entries exist. Adding a field would
    require a chain version marker and verification that branches on it.
    """
    content = {
        "organization_id": _canonical(organization_id),
        "chain_position": chain_position,
        "previous_hash": previous_hash,
        "actor_type": actor_type,
        "actor_id": _canonical(actor_id),
        "actor_role": actor_role,
        "action_type": action_type,
        "entity_type": entity_type,
        "entity_id": _canonical(entity_id),
        "before_state": _canonical(before_state),
        "after_state": _canonical(after_state),
        "correlation_id": correlation_id,
        "event_id": _canonical(event_id),
        "occurred_at": _canonical(occurred_at),
    }

    # sort_keys makes ordering deterministic; separators removes the whitespace
    # json.dumps would otherwise insert. Both are required for reproducibility.
    serialised = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(serialised.encode("utf-8")).hexdigest()
