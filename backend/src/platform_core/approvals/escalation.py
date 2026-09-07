"""
The escalation sweeper — chasing overdue approvals.

WHAT IT DOES
    Runs on a schedule. For every organisation, finds Pending approval requests
    past their deadline and either reminds or escalates, according to the SLA
    policy's `escalation_after_misses`.

THE SPEC'S RULE
    "Unactioned approvals escalate after a configurable window (default 2
    business days)" for job approval, and for interview feedback "overdue
    triggers a reminder; a second miss escalates". So the sweeper reminds first
    and escalates on the configured miss count, rather than escalating
    immediately.

WHY IT ITERATES ORGANISATIONS
    Same reason as the outbox relay: the tables are tenant-scoped and carry
    row-level security. A sweeper that queried across tenants would be a
    privileged code path in a scheduled job, which is the shape of thing that
    leaks. It lists organisation IDs through a system session — the documented
    legitimate use — then works inside each tenant's context.

ON CLOCKS
    `due_at` is computed by the application, because business-day arithmetic
    against a holiday calendar is not something to express in SQL. It is
    therefore compared against the application clock too, keeping both sides of
    the comparison on one clock — the same rule the relay follows, applied the
    other way round.

    A few milliseconds of skew is immaterial here in any case: these deadlines
    are days away, not seconds.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select

from platform_core.db.types import uuid7
from platform_core.events.catalog import EventType
from platform_core.events.emitter import emit_event
from platform_core.models.approval import (
    ApprovalAction,
    ApprovalActionType,
    ApprovalRequest,
    ApprovalStatus,
)
from platform_core.models.sla_policy import SLAPolicy
from platform_core.tenancy.context import organization_context, system_context

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SweepResult:
    """What one sweep did."""

    reminders_sent: int = 0
    escalations: int = 0

    def __add__(self, other: "SweepResult") -> "SweepResult":
        return SweepResult(
            reminders_sent=self.reminders_sent + other.reminders_sent,
            escalations=self.escalations + other.escalations,
        )


async def sweep_organization() -> SweepResult:
    """
    Process overdue approvals for the organisation currently in context.

    Returns:
        SweepResult: counts of reminders sent and escalations raised.

    Each overdue request either gets a reminder or is escalated, never both in
    one sweep. Escalation happens once `reminder_count` reaches the policy's
    `escalation_after_misses`, so a policy of 1 escalates on the first sweep
    after the deadline and a policy of 2 reminds first.
    """
    from platform_core.db.session import get_session

    now = datetime.now(UTC)
    reminders = 0
    escalations = 0

    async with get_session() as session:
        result = await session.execute(
            select(ApprovalRequest)
            .where(ApprovalRequest.status == ApprovalStatus.PENDING.value)
            .where(ApprovalRequest.due_at.is_not(None))
            .where(ApprovalRequest.due_at <= now)
        )
        overdue = list(result.scalars().all())

        for request in overdue:
            policy = None
            if request.sla_policy_id is not None:
                policy = await session.get(SLAPolicy, request.sla_policy_id)

            # No policy means no configured escalation behaviour. Default to
            # escalating on the first miss rather than never — an approval that
            # is overdue and silent is worse than one that escalates early.
            misses_before_escalation = policy.escalation_after_misses if policy is not None else 1

            if request.reminder_count < misses_before_escalation:
                request.reminder_count += 1
                session.add(request)
                session.add(
                    ApprovalAction(
                        id=uuid7(),
                        organization_id=request.organization_id,
                        approval_request_id=request.id,
                        action=ApprovalActionType.REMINDED.value,
                        actor_id=None,  # the system reminded, not a person
                    )
                )
                await emit_event(
                    session,
                    event_type=EventType.APPROVAL_REMINDER_SENT,
                    entity_type="ApprovalRequest",
                    entity_id=request.id,
                    application_id=request.application_id,
                    payload={
                        "approval_type": request.approval_type,
                        "reminder_count": request.reminder_count,
                        "assigned_to": str(request.assigned_to_user_id),
                    },
                )
                reminders += 1
                continue

            # --- Escalate ---------------------------------------------------
            # Status becomes ESCALATED, not a terminal state: the request still
            # needs an answer, it is simply being asked of someone else now.
            #
            # escalated_to_user_id is left null here. Resolving the escalation
            # target requires the notification service to know who currently
            # holds the capability, which arrives with Phase 2. Until then the
            # event carries the required capability and the escalation surfaces
            # on the approvals dashboard, where any holder can pick it up.
            request.status = ApprovalStatus.ESCALATED.value
            request.escalated_at = now
            session.add(request)
            session.add(
                ApprovalAction(
                    id=uuid7(),
                    organization_id=request.organization_id,
                    approval_request_id=request.id,
                    action=ApprovalActionType.ESCALATED.value,
                    actor_id=None,
                )
            )
            await emit_event(
                session,
                event_type=EventType.APPROVAL_ESCALATED,
                entity_type="ApprovalRequest",
                entity_id=request.id,
                application_id=request.application_id,
                payload={
                    "approval_type": request.approval_type,
                    "required_capability": request.required_capability,
                    "original_assignee": str(request.assigned_to_user_id),
                    "reminders_sent": request.reminder_count,
                    "overdue_since": request.due_at.isoformat() if request.due_at else None,
                },
            )
            escalations += 1
            logger.warning(
                "Approval escalated after missing its deadline",
                extra={
                    "approval_type": request.approval_type,
                    "reminders_sent": request.reminder_count,
                },
            )

    return SweepResult(reminders_sent=reminders, escalations=escalations)


async def sweep_all_organizations() -> SweepResult:
    """
    Run one sweep across every organisation. The scheduled job's entry point.

    Returns:
        SweepResult: totals across all organisations.
    """
    from sqlalchemy import text

    from platform_core.db.session import get_system_session

    with system_context():
        async with get_system_session() as session:
            rows = await session.execute(text("SELECT id FROM organizations"))
            organization_ids = [row[0] for row in rows]

    total = SweepResult()
    for organization_id in organization_ids:
        with organization_context(organization_id):
            total = total + await sweep_organization()

    if total.reminders_sent or total.escalations:
        logger.info(
            "Approval sweep complete",
            extra={
                "reminders_sent": total.reminders_sent,
                "escalations": total.escalations,
                "organizations": len(organization_ids),
            },
        )
    return total
