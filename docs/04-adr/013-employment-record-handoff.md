# ADR-013: Hand off employment records rather than retain them

**Status:** Accepted
**Date:** 2026-08-30
**Decision Log ref:** C-04, G-05

## Context

When a candidate is hired, their Aadhaar, PAN, EPFO details and signed offer stop being recruitment data and become employment records. Those are governed by EPF, Income Tax and state Shops & Establishments rules, with retention running to years and measured from **end of employment**.

This platform never observes end of employment. Scope ends at `Onboarded` — no payroll, no attendance, no exit event. "Retain for N years from exit" is therefore unimplementable here, and degrades in practice into retain-forever.

Retain-forever means accumulating the highest-sensitivity data in the system indefinitely, for data we have no product reason to hold, while becoming a more attractive breach target.

## Decision

At `Onboarded` plus a configurable window (default 90 days), assemble an **Employment Record Pack** and export it to the customer's system of record. On confirmed export, destroy the documents, signed offer and identifying profile fields here. The anonymised Application Analytics Record is retained.

The pack is a versioned, documented export contract: structured JSON (identity, offer terms, CTC breakdown with rule set version, joining date, BGV outcome) plus documents and signed offer PDF, with a manifest and per-file hashes.

**Nothing is destroyed without a confirmed successful handoff.** Export failure retries with backoff, then alerts. Customers with no HRMS get `AdminHold`: the pack is made available for download and an Admin confirms receipt to trigger the purge.

## Consequences

The scope boundary in the spec becomes structurally true rather than a statement of intent. Employment records live where employment records belong.

The longest retention clock in the system drops to 24 months (talent pool consent) rather than a multi-year employment period. Backup retention shortens correspondingly, which is a useful side effect.

Ninety days covers onboarding corrections — a reissued document, a corrected EPFO detail — while staying well short of a period where we would be choosing to hold employment records.

The cost: if we later build payroll or an HRMS, existing customers' historical employee documents are gone from our side. The customer holds the pack, so re-ingestion is possible if they supply it. DPDP purpose limitation would require fresh notice for that repurposing regardless, so this is not a cost created by the handoff.

A future HRMS module becomes another implementation of the same export contract, which is why the pack is specified as a versioned interface rather than an ad-hoc dump.

## Alternatives considered

**Retain for the statutory period** — requires knowing end of employment, which we do not. Would become indefinite retention by default.

**Retain for a fixed long period, say eight years** — defensible against Companies Act §128(5), but holds the most sensitive data in the platform for years with no product justification.

**Purge immediately at Onboarded** — no window for onboarding corrections, and no chance to confirm the customer actually received the records.
