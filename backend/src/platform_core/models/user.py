"""
User — an internal person who signs in.

WHO IS A USER
    HR, Hiring Managers, Interviewers, Admins, and employees who submit
    referrals. Everyone who authenticates through the organisation's identity
    provider.

WHO IS NOT
    Candidates. They hold no account by design (Spec §Candidate Experience) and
    act through expiring portal tokens scoped to a single Application. Modelling
    them as Users would give them an identity in the tenant's directory, which
    is both wrong and a larger attack surface.

TENANT-SCOPED
    A User belongs to exactly one organisation. A person working across two
    customer organisations has two User rows, which is correct: their
    permissions, their audit trail and their data access are separate in each.
"""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from platform_core.db.base import TenantModel


class UserStatus(StrEnum):
    """
    Lifecycle of an internal account.

    Note there is no "deleted". A user who leaves becomes OFFBOARDED and their
    row remains, because audit entries, approvals and interview feedback all
    reference them. Deleting the row would orphan history that must stay
    readable (ADR-016).
    """

    ACTIVE = "Active"
    SUSPENDED = "Suspended"  # temporarily blocked; capabilities do not apply
    OFFBOARDED = "Offboarded"  # left the organisation; row retained for audit


class User(TenantModel):
    """An internal user account."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # The organisation's own identifier for this person. Optional, because not
    # every customer has one, and useful for reconciling against their HRMS.
    employee_code: Mapped[str | None] = mapped_column(String(64), nullable=True)

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=UserStatus.ACTIVE.value
    )

    # --- SSO linkage --------------------------------------------------------
    # The subject claim from the identity provider: SAML NameID, or OIDC `sub`.
    # This, not email, is the durable link to the external identity — people
    # change their email address and keep the same account.
    external_idp_subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    idp_config_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("identity_provider_configs.id", ondelete="SET NULL"),
        nullable=True,
    )

    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def is_active(self) -> bool:
        """
        Whether this account may currently act.

        Checked during capability resolution: a suspended or offboarded user
        resolves to zero capabilities regardless of what roles they still hold.
        Revoking access by status is one operation; unpicking role assignments
        is many, and the difference matters when someone leaves under a cloud.
        """
        return self.status == UserStatus.ACTIVE

    def __repr__(self) -> str:
        return f"<User {self.email!r} status={self.status} org={self.organization_id}>"
