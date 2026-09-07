"""
Shared-kernel ORM models.

Only entities used by every module live here. Domain entities (Job Posting,
Candidate Profile, Application and so on) belong to their own modules under
src/modules/ from Phase 2 onward.

IMPORTANT: every model must be imported here. Alembic's --autogenerate compares
the live database against Base.metadata, and a model it cannot see looks like a
table that should be dropped.
"""

from platform_core.models.approval import (
    ApprovalAction,
    ApprovalActionType,
    ApprovalRequest,
    ApprovalStatus,
    ApprovalType,
)
from platform_core.models.audit_entry import GENESIS_HASH, AuditEntry
from platform_core.models.delegation import ApprovalDelegation
from platform_core.models.feature_flag import FeatureFlag, FlagKey
from platform_core.models.identity_provider import IdentityProviderConfig, IdpProtocol
from platform_core.models.organization import Organization
from platform_core.models.outbox_event import OutboxEvent, OutboxStatus
from platform_core.models.processed_event import ProcessedEvent
from platform_core.models.role import Role, RoleAssignment, ScopeType
from platform_core.models.sla_policy import (
    EscalationTarget,
    Holiday,
    SLAPolicy,
    SLAType,
)
from platform_core.models.user import User, UserStatus

__all__ = [
    "ApprovalAction",
    "ApprovalActionType",
    "ApprovalDelegation",
    "ApprovalRequest",
    "ApprovalStatus",
    "ApprovalType",
    "AuditEntry",
    "EscalationTarget",
    "Holiday",
    "SLAPolicy",
    "SLAType",
    "GENESIS_HASH",
    "FeatureFlag",
    "FlagKey",
    "IdentityProviderConfig",
    "IdpProtocol",
    "Organization",
    "OutboxEvent",
    "OutboxStatus",
    "ProcessedEvent",
    "Role",
    "RoleAssignment",
    "ScopeType",
    "User",
    "UserStatus",
]
