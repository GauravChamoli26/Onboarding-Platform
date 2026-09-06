"""
IdentityProviderConfig — per-organisation SSO settings.

WHY THIS IS PER ORGANISATION
    Each enterprise customer brings their own identity provider: Okta, Entra ID,
    Google Workspace, a self-hosted Keycloak. Multi-tenant SSO means storing one
    configuration per tenant rather than one for the platform.

    This is also the requirement that ruled out every hosted SSO product, since
    all of them sit outside the residency boundary — so the service provider is
    implemented directly (ADR-006).

NOT USED YET
    Phase 1's later units implement the SAML and OIDC flows. The table exists
    now because User references it, and adding a foreign key later is a
    migration nobody enjoys.
"""

from enum import StrEnum
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from platform_core.db.base import TenantModel


class IdpProtocol(StrEnum):
    """Federation protocol."""

    SAML2 = "SAML2"
    OIDC = "OIDC"


class IdentityProviderConfig(TenantModel):
    """One organisation's identity provider configuration."""

    __tablename__ = "identity_provider_configs"

    protocol: Mapped[str] = mapped_column(String(16), nullable=False)

    display_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # SAML: the IdP metadata URL. OIDC: the discovery document URL.
    metadata_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # OIDC client credentials. The SECRET is a pointer into AWS Secrets Manager,
    # never the value itself — a secret in a database column ends up in every
    # backup, every replica and every debugging dump of that row.
    client_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_secret_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # SAML signing certificate, likewise stored as a reference.
    certificate_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Maps IdP claim names to our user fields, because every provider names them
    # differently: {"email": "mail", "full_name": "displayName"}.
    attribute_mapping: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    # Just-in-time provisioning: create a User on first successful login rather
    # than requiring one to exist. Convenient, and a deliberate decision per
    # customer — it means anyone their IdP authenticates gets an account here.
    jit_provisioning_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    # Role granted to JIT-provisioned users. Should be the least privileged one
    # the customer can tolerate.
    default_role_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="SET NULL"),
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    def __repr__(self) -> str:
        return f"<IdentityProviderConfig {self.protocol} {self.display_name!r}>"
