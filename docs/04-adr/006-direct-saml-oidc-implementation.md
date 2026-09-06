# ADR-006: Direct SAML/OIDC service provider implementation

**Status:** Accepted
**Date:** 2026-08-30
**Decision Log ref:** A-09

## Context

Internal users authenticate via their organisation's identity provider — SAML 2.0 or OIDC, configured per organisation. Multi-tenant SSO with per-customer IdP configuration is a standard enterprise requirement.

It is also a solved problem, commercially. WorkOS, Auth0, Clerk and Cognito federation all handle it well.

All of them are hosted outside India.

## Decision

Implement the service provider directly: `Authlib` for OIDC, `python3-saml` for SAML. Per-organisation IdP configuration lives in the `Identity Provider Config` entity.

## Consequences

Authentication stays inside the residency boundary, consistent with the posture applied to hosting, inference, error tracking and feature flags. Applying that posture everywhere except the authentication path would be incoherent.

The cost is real: budget two weeks, and expect enterprise customers to each bring IdP quirks. SAML in particular has a long tail of implementation variance.

It is mostly write-once. SAML has not changed materially in years.

## Alternatives considered

**Keycloak self-hosted in ap-south-1** — the one viable off-the-shelf option that respects residency. Rejected because running and upgrading Keycloak is a permanent operational commitment, and the team would rather maintain SAML code than a Java identity server. This is a genuinely close call; a team with different preferences should take Keycloak.

**WorkOS or Auth0** — would save weeks. Rejected on residency alone.

**Cognito** — per-tenant SAML federation gets awkward at the user-pool level, and it does not solve the residency question cleanly either.
