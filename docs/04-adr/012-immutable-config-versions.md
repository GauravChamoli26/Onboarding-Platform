# ADR-012: Immutable version rows for versioned configuration

**Status:** Accepted
**Date:** 2026-08-30
**Decision Log ref:** E-04, A-12 (SDD §0)

## Context

Several configuration entities are referenced by records that must remain reproducible years later: CTC Rule Set (an offer letter is a legal instrument), Approval Band Policy (a band check must stay explicable), Pipeline Template (a candidate's pipeline must not be rewritten mid-flight), Notification Template (DLT registration is per-template), Model Version (fairness sign-off attaches to it).

An earlier draft stored a foreign key to the "version" and let the row be edited in place. The FK looks like a snapshot and is not one.

## Decision

Once a version row reaches `Active`, it is **immutable**. Edits create a new version row. Enforced by a database trigger rejecting `UPDATE`, not by convention.

Consumers store the version foreign key. Where the content is small and the guarantee matters most — JD text on a Job Posting — an inline copy is used instead.

## Consequences

The promise that "a template change never retroactively rewrites a live candidate's pipeline" is structurally true rather than aspirational.

A retired CTC rule set still reproduces the exact breakdown printed on an offer letter from eighteen months ago. In a dispute, that matters.

The cost is more rows and a slightly heavier editing flow — changing an HRA percentage means creating a version, not editing a field. That friction is appropriate for configuration with legal consequences.

Three different versioning patterns coexist deliberately (inline copy, immutable version plus FK, entity versioning). SDD §0 documents which applies where. Mixing them without documenting the rule was a defect in an earlier revision.

## Alternatives considered

**Edit in place with an audit trail** — the audit log would record what changed, but reconstructing the exact rule set that produced a historical breakdown becomes an archaeology exercise.

**Event-sourced configuration** — fully general, and more machinery than this needs.
