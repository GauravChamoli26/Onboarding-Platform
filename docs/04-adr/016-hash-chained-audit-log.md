# ADR-016: Append-only hash-chained audit log

**Status:** Accepted
**Date:** 2026-08-30
**Decision Log ref:** B-08

## Context

The spec requires that every status change, feedback entry, approval, decision, note, consent action and merge is "logged immutably and exportably". Views of unmasked sensitive PII must emit `SensitiveDataAccessed`.

"Immutably" without a mechanism is an adjective. A normal database table is editable by anyone with write access, including anyone who compromises the application.

The audit log is also the evidence base for a discrimination challenge, a DPDP inquiry, or an internal investigation into PII misuse — situations where the person with the strongest motive to alter it may be an insider with database access.

## Decision

Append-only table with `REVOKE UPDATE, DELETE` from all application roles, plus a hash chain: each entry hashes its own content together with the previous entry's hash. Entries carry a monotonic `sequence_number`.

A nightly job verifies the chain. A break is a priority alert.

Audit entries are never rewritten — including after a Candidate Profile merge, where they retain the original profile IDs and resolve through the merge chain at read time.

## Consequences

Tampering is detectable rather than merely discouraged. Deleting or altering an entry breaks the chain at that point and every point after it.

The audit log is never purged. It contains no free-text PII by construction — it records identifiers, actors and state transitions — so it sits outside the retention clocks entirely. That constraint has to be respected when adding new audit entry types.

Storage grows monotonically. At this volume that is immaterial for many years.

Verification cost is a nightly full-chain walk. If that becomes slow, checkpointing is the standard remedy.

## Alternatives considered

**Standard table with restricted permissions** — stops casual modification, not a determined one, and provides no evidence either way.

**External append-only service or blockchain-style ledger** — stronger guarantees, more moving parts, and residency questions for managed offerings. The hash chain gives most of the benefit at a fraction of the cost.
