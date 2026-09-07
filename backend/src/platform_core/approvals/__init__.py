"""
The shared approval engine.

    business_days.py  business-day arithmetic against a holiday calendar
    engine.py         requesting, routing and resolving approvals
    escalation.py     the scheduled sweeper for overdue requests

Replaces three nullable `approver_id` columns scattered across Job Posting,
Negotiation Log and Offer (Decision Log G1). Delegation, escalation, deadlines
and a unified approvals queue were all unbuildable against that shape.

Three modules depend on this: job publish (Module 1), above-band CTC approval
(Module 5), and offer letter approval (Module 7).
"""

from platform_core.approvals.business_days import (
    add_business_days,
    business_days_between,
    is_business_day,
)
from platform_core.approvals.engine import (
    ApprovalError,
    approve,
    compute_due_at,
    reject,
    request_approval,
    resolve_assignee,
    withdraw,
)
from platform_core.approvals.escalation import (
    SweepResult,
    sweep_all_organizations,
    sweep_organization,
)

__all__ = [
    "ApprovalError",
    "SweepResult",
    "add_business_days",
    "approve",
    "business_days_between",
    "compute_due_at",
    "is_business_day",
    "reject",
    "request_approval",
    "resolve_assignee",
    "sweep_all_organizations",
    "sweep_organization",
    "withdraw",
]
