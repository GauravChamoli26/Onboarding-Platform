# ADR-009: Terraform with a self-managed in-region state backend

**Status:** Accepted
**Date:** 2026-08-30
**Decision Log ref:** A-11

## Context

Infrastructure as code for AWS ap-south-1 with DR in ap-south-2. The team is Python-heavy, which initially made AWS CDK in Python attractive — one language across application and infrastructure.

That argument rested on the team having no dedicated infrastructure capacity. It does have one.

## Decision

Terraform, with state in a **self-managed S3 bucket in ap-south-1**, DynamoDB state locking, and SSE-KMS encryption. Directory-per-environment with shared modules, not workspaces.

## Consequences

Portable across clouds, largest hiring pool, and the DevOps engineer works in their primary tool rather than a Python DSL.

The state backend decision matters more than it looks. Terraform Cloud is where most teams land by default, and it is US-hosted. State files carry full infrastructure topology and occasionally secrets leaked through outputs. That is not candidate PII, so it is a weaker case than the error-tracking one — but it is inconsistent with a posture where we require written residency attestations from external processors. Self-managed costs nothing extra and keeps the story coherent. Migrating state later is irritating, so this is decided up front.

Directory-per-environment is more verbose than workspaces and much easier for someone new to read.

Terraform's BUSL licence restricts building competing products, not internal infrastructure use. It does not affect us, so OpenTofu is not worth the detour.

## Alternatives considered

**AWS CDK in Python** — one language, appealing for a small Python team. Rejected once dedicated DevOps capacity was confirmed.

**Terraform Cloud** — better collaboration features, out of region.

**Pulumi** — Python-native and cloud-agnostic, smaller community.
