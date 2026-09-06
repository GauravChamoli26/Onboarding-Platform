# ADR-014: Residency enforced by fail-closed adapters

**Status:** Accepted
**Date:** 2026-08-30
**Decision Log ref:** C-01

## Context

DPDP permits cross-border transfer by default, with no broad country restrictions currently in force. India hosting is therefore not strictly mandated for recruitment data.

We adopt it anyway: the platform stores Aadhaar, PAN and EPFO details, and India hosting is the expected posture for sensitive personal data in audit and in enterprise procurement.

The failure mode for residency commitments is that they live in documentation. Someone adds a feature, points it at a convenient US endpoint, and nothing objects.

## Decision

Residency is a runtime control, not a policy statement.

- Application, database and object storage in AWS Mumbai (ap-south-1); DR in Hyderabad (ap-south-2)
- LLM inference on India-region endpoints only. **The adapter asserts the region per call and fails closed** on a non-India endpoint for any PII-bearing payload
- Encryption keys in India-region KMS
- Terraform state, error tracking and feature flags all in-region or self-hosted (ADR-009, A-13, A-14)
- Written residency attestation required from every third-party processor before contract

A forced non-India endpoint in test must cause the call to fail, not to succeed with a logged warning. That is an acceptance criterion.

## Consequences

The residency commitment is enforceable and testable rather than aspirational.

It rules out a lot of otherwise-default developer tooling: Sentry SaaS, LaunchDarkly, Auth0, WorkOS, Terraform Cloud. Each has an in-region or self-hosted replacement, and each replacement carries a cost — most visibly the two weeks for direct SAML/OIDC implementation (ADR-006).

Model availability differs by region. Bedrock in Mumbai does not carry every model available in US regions, and that constrains model selection. Verify at build time; regional availability changes.

ap-south-2 has a smaller service catalogue than ap-south-1. The DR path must be verified against actual service availability, not assumed.

## Alternatives considered

**Document the commitment, enforce by review** — the standard approach and the one that quietly fails. Rejected.

**Cross-border transfer where convenient** — legally permissible today. Rejected because the audit and procurement posture matters more than the convenience, and because the law may not stay this way.
