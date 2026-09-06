"""
Role and RoleAssignment — how capabilities reach a user.

THE SHAPE
    Role holds a set of capabilities. RoleAssignment grants a Role to a User,
    optionally scoped to part of the organisation and optionally with an expiry.

    A user's effective capabilities are the union of every unexpired assignment
    they hold — provided their account is Active.

WHY ASSIGNMENTS ARE SCOPED
    The permission matrix says a Hiring Manager may search the Talent Pool for
    "own reqs", and an Interviewer may add notes on "own round only". Those are
    not different roles; they are the same role bounded to part of the
    organisation. Without scope on the assignment, the only ways to express them
    are proliferating roles or hard-coded special cases, and both rot.

WHY ASSIGNMENTS EXPIRE
    Maternity cover, a contractor on a three-month engagement, someone acting up
    while a manager is away. Access that has to be remembered to be removed is
    access that stays.
"""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import ARRAY, Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from platform_core.db.base import TenantModel


class ScopeType(StrEnum):
    """
    What an assignment is bounded to.

    ORGANIZATION is the default and means unrestricted within the tenant.
    DEPARTMENT and JOB_POSTING narrow it, with `scope_id` naming the specific
    department or posting.
    """

    ORGANIZATION = "Organization"
    DEPARTMENT = "Department"
    JOB_POSTING = "JobPosting"


class Role(TenantModel):
    """A named bundle of capabilities, per organisation."""

    __tablename__ = "roles"

    # HR, HiringManager, Interviewer, Employee, Admin — or a custom name.
    role_key: Mapped[str] = mapped_column(String(64), nullable=False)

    # Capability names as a text array. Postgres arrays are queryable
    # (`'shortlist' = ANY(capabilities)`) which JSON would make clumsier, and
    # they stay readable in an audit export a decade from now (SDD §0).
    capabilities: Mapped[list[str]] = mapped_column(
        ARRAY(String(64)), nullable=False, server_default="{}"
    )

    description: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # True for the five roles seeded with every organisation. Admins may edit
    # their capabilities but not delete them — removing the HR role from a live
    # organisation is not a recoverable action.
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    def __repr__(self) -> str:
        return f"<Role {self.role_key} caps={len(self.capabilities)}>"


class RoleAssignment(TenantModel):
    """A grant of a Role to a User, optionally scoped and time-bounded."""

    __tablename__ = "role_assignments"

    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # CASCADE here, unlike elsewhere: an assignment has no meaning without its
    # user, and the User row itself is never deleted (see UserStatus), so this
    # only fires in genuine cleanup.

    role_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # RESTRICT: deleting a role that is still assigned should fail loudly rather
    # than silently stripping people's access.

    scope_type: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=ScopeType.ORGANIZATION.value
    )
    # Null when scope_type is ORGANIZATION; otherwise the department or posting.
    scope_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    granted_by: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Null means indefinite. A value in the past means the assignment grants
    # nothing — enforced during capability resolution, not by a cleanup job, so
    # that a missed job run cannot leave access alive.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<RoleAssignment user={self.user_id} role={self.role_id} scope={self.scope_type}>"
