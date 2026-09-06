"""
Audit chain verification.

WHAT THIS DETECTS
    Any alteration to a stored entry, any deletion, and any insertion. Changing
    one entry changes its hash, which breaks the link every later entry depends
    on, so a single edit invalidates the whole tail of the chain.

    That is the property that makes tampering visible rather than merely
    discouraged. Prevention (the trigger and the revoked grants) can be undone
    by someone with enough privilege. Detection is what remains.

WHEN IT RUNS
    Nightly, per organisation, as a scheduled job. A break is a priority alert —
    it means either a bug in the writer or an attempt to alter history, and both
    warrant waking someone.

COST
    A full walk is O(n) in entries and reads every row. At this volume that is
    fine for years. If it ever is not, the standard remedy is checkpointing:
    verify from the last known-good position rather than from genesis.
"""

import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.audit.hashing import compute_entry_hash
from platform_core.models.audit_entry import GENESIS_HASH, AuditEntry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VerificationResult:
    """Outcome of verifying one organisation's chain."""

    organization_id: UUID
    entries_checked: int
    is_valid: bool
    # Chain position of the first problem found, if any. Everything after it is
    # suspect too, so only the first is reported — the rest are consequences.
    first_invalid_position: int | None = None
    failure_reason: str | None = None

    def __str__(self) -> str:
        if self.is_valid:
            return (
                f"Chain valid: {self.entries_checked} entries "
                f"for organisation {self.organization_id}"
            )
        return (
            f"CHAIN BROKEN at position {self.first_invalid_position} "
            f"for organisation {self.organization_id}: {self.failure_reason}"
        )


async def verify_chain(session: AsyncSession, organization_id: UUID) -> VerificationResult:
    """
    Walk an organisation's audit chain and verify every link.

    Three things are checked at each entry:

    1. The stored hash matches a recomputation from the entry's own content.
       Catches modification of any field.
    2. The entry's previous_hash matches the preceding entry's hash.
       Catches insertion, and reordering.
    3. Chain positions are consecutive from 1 with no gaps.
       Catches deletion, which the other two would otherwise miss — removing a
       whole entry leaves the surviving links intact between its neighbours only
       if positions are not checked.

    Args:
        session: a tenant-scoped session for this organisation.
        organization_id: the organisation whose chain to verify. Must match the
            session's tenant, or row-level security will show no entries.

    Returns:
        VerificationResult: valid, or the position and reason of the first
        problem.
    """
    result = await session.execute(select(AuditEntry).order_by(AuditEntry.chain_position))
    entries = list(result.scalars().all())

    if not entries:
        return VerificationResult(organization_id=organization_id, entries_checked=0, is_valid=True)

    expected_previous = GENESIS_HASH

    for index, entry in enumerate(entries, start=1):
        # --- 3. Positions are consecutive from 1 ---------------------------
        if entry.chain_position != index:
            return VerificationResult(
                organization_id=organization_id,
                entries_checked=index,
                is_valid=False,
                first_invalid_position=entry.chain_position,
                failure_reason=(
                    f"Gap in chain: expected position {index}, "
                    f"found {entry.chain_position}. An entry has been removed."
                ),
            )

        # --- 2. The link to the previous entry holds -----------------------
        if entry.previous_hash != expected_previous:
            return VerificationResult(
                organization_id=organization_id,
                entries_checked=index,
                is_valid=False,
                first_invalid_position=entry.chain_position,
                failure_reason=(
                    "previous_hash does not match the preceding entry. "
                    "An entry has been inserted, reordered, or altered."
                ),
            )

        # --- 1. The entry's own content is unaltered -----------------------
        recomputed = compute_entry_hash(
            organization_id=entry.organization_id,
            chain_position=entry.chain_position,
            previous_hash=entry.previous_hash,
            actor_type=entry.actor_type,
            actor_id=entry.actor_id,
            actor_role=entry.actor_role,
            action_type=entry.action_type,
            entity_type=entry.entity_type,
            entity_id=entry.entity_id,
            before_state=entry.before_state,
            after_state=entry.after_state,
            correlation_id=entry.correlation_id,
            event_id=entry.event_id,
            occurred_at=entry.occurred_at,
        )
        if recomputed != entry.entry_hash:
            return VerificationResult(
                organization_id=organization_id,
                entries_checked=index,
                is_valid=False,
                first_invalid_position=entry.chain_position,
                failure_reason=(
                    "Stored hash does not match the entry's content. This entry has been modified."
                ),
            )

        expected_previous = entry.entry_hash

    return VerificationResult(
        organization_id=organization_id,
        entries_checked=len(entries),
        is_valid=True,
    )


async def verify_all_chains() -> list[VerificationResult]:
    """
    Verify every organisation's chain. The nightly job's entry point.

    Iterates organisations rather than querying across them, for the same reason
    the relay does: a query spanning tenants is the shape of thing that leaks,
    and there is no need for one here.

    Returns:
        list[VerificationResult]: one result per organisation.
    """
    from sqlalchemy import text

    from platform_core.db.session import get_session, get_system_session
    from platform_core.tenancy.context import organization_context, system_context

    with system_context():
        async with get_system_session() as session:
            rows = await session.execute(text("SELECT id FROM organizations"))
            organization_ids = [row[0] for row in rows]

    results: list[VerificationResult] = []

    for organization_id in organization_ids:
        with organization_context(organization_id):
            async with get_session() as session:
                result = await verify_chain(session, organization_id)
                results.append(result)

                if not result.is_valid:
                    # ERROR, not warning. A broken audit chain means either a
                    # writer bug or an attempt to alter history, and both
                    # warrant waking someone.
                    logger.error(
                        "Audit chain verification failed",
                        extra={
                            "organization_id": str(organization_id),
                            "first_invalid_position": result.first_invalid_position,
                            "failure_reason": result.failure_reason,
                        },
                    )

    return results
