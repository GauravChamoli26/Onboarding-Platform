# Employee Onboarding & Recruitment Platform
# 00 — Documentation Index

**Last updated:** 30 August 2026
**Status of the set:** Spec sealed at V3.3. Design and roadmap current. Build has not started.

Start here. This page explains what each document is for, who it is for, and which one answers your question.

---

## The document set

| # | Document | Answers | Primary audience | Status |
|---|---|---|---|---|
| **00** | Documentation Index | "Where do I find X?" | Everyone | Living |
| **01** | Decision Log | "Why is it like this, and who decided?" — including what is deliberately *not* built yet, and what triggers it | Everyone | Living |
| **02** | Build Spec V3.3 | "What does the product do?" | Product, HR, engineering, sales | **Sealed** |
| **03** | Solution Design Document 3.0 | "How is it built?" | Engineering | **Sealed** |
| **04** | Architecture Decision Records | "Why this technology and not that one?" | Engineering | Living |
| **05** | Data Protection & Compliance | "How do we stay legal?" | Legal, security, enterprise buyers | **Not yet written** |
| **06** | Stack & Roadmap | "What are we building when?" | Everyone | Living |
| **07** | Test Strategy | "How do we know it works?" | Engineering, QA | **Not yet written** — see SDD §7 |
| **08** | Glossary & Onboarding Guide | "What does that word mean?" | New joiners | **Not yet written** |

Documents marked *not yet written* are planned, not lost. 05 matters most: it
consolidates the compliance material currently spread across 02 and 03 into the
form an enterprise security questionnaire actually asks for, and it is worth
having before a design partner's legal review rather than during it.

**Sealed** means changes require a change-control entry in the Decision Log, not a quiet edit. **Living** means the document is expected to change as the project moves.

---

## Reading paths

Pick the one that matches why you're here.

**New engineer, day one.**
02 (Spec, Overview and Modules) → 03 (SDD, Sections 0–2) → 06 (Roadmap, Part 1) → 04 (ADRs) → `backend/README.md` to get it running. Budget half a day. Do not start with the SDD data model; it will not make sense without the spec.

**New product or HR stakeholder.**
02 (Spec) alone, then 01 (Decision Log) for anything that looks surprising. You do not need 03, 04 or 07.

**Legal or compliance review.**
Until 05 exists: 02 §Cross-Cutting Requirements and §Retention, then SDD §4.6 (retention) and §1.4 (application security).

**Enterprise customer security questionnaire.**
SDD §1.4 (Application Security) and §6 (Non-Functional), plus ADR-002, ADR-010, ADR-014 and ADR-016. Most questionnaires are answerable from those.

**Investor or diligence.**
06 (Roadmap) for scope and timeline, 01 (Decision Log) for how decisions get made, 05 for compliance posture.

**"Why did we decide X?"**
01 (Decision Log) always. Every decision has an ID, a date, a rationale and a reversibility rating.

**"Is this built yet?"**
01 §I (Deferred build items). Anything designed but not built is listed there with the trigger that makes it required. If it is not in §I and not built, that is a gap rather than a decision — raise it.

---

## The chain of authority

When two documents disagree, this is the order that wins:

```
02  Build Spec          ── what the product does. Functional truth.
      │
      ▼
03  Solution Design     ── how it is built. Derives from the spec.
      │
      ├──▶ 04  ADRs               ── individual technology choices
      ├──▶ 05  Data Protection    ── the compliance view of the same system
      └──▶ 07  Test Strategy      ── how each requirement is verified

06  Stack & Roadmap     ── sequencing and delivery. Derives from both.
01  Decision Log        ── the record. Explains all of the above.
```

If the SDD contradicts the Spec, the Spec wins and the SDD is wrong. If the Roadmap contradicts either, the Roadmap is wrong. Raise it rather than working around it.

---

## How change control works

The Spec (02) and the SDD (03) are sealed. That does not mean frozen — it means changes are visible.

1. Anyone can propose a change. Raise it against the document and section.
2. Product and tech lead decide. Legal is required for anything touching consent, retention, PII or a document a candidate signs.
3. **Add a Decision Log entry** (01) with an ID, date, rationale and reversibility.
4. Edit the document, with a changelog line at the top.
5. Version bump only for a batch of changes, not for each one.

The point is that a year from now, someone should be able to reconstruct why the system looks the way it does. Changes that skip step 3 defeat the whole set.

---

## Current status at a glance

**Settled and not being reopened:** technology stack, data model, event contracts, security design, CTC structure, retention model, roles and permissions.

**Settled for now, deliberately reopenable:** AI voice screening (deferred, integration seam preserved), AI Copilot scoring outputs (deferred pending a validation corpus), BGV vendor (module built, contract deferred), LinkedIn API (manual posting at launch).

**Genuinely open:**

| Item | Owner | Needed by |
|---|---|---|
| Approval band thresholds per designation | HR/Finance | Interim default in place; no deadline |
| Wage Code 50% denominator confirmation | Legal | Before Phase 6 |
| Gifteko sub-processor agreement + customer DPA disclosure | Legal | Before first customer |
| Kit branding onboarding for the design partner | Gifteko ops | **Week 4 — multi-week lead time** |
| Fairness sign-off permanent owner | Leadership | Before scale |
| Naukri RMS subscription — worth the cost at launch? | Product | Week 12 |

---

## Where things live

```
.
├── .github/workflows/ci.yml   CI. Must be at the repository ROOT — GitHub
│                              discovers workflows nowhere else.
├── docs/                      This documentation set.
│   └── 04-adr/                One file per architecture decision.
└── backend/                   Python service. See backend/README.md to run it.
    ├── src/platform_core/     Shared kernel: config, db, tenancy, auth,
    │                          api, events, audit, observability, models.
    ├── alembic/versions/      Migrations. RLS policies are hand-written here.
    ├── tests/                 Test suite. The isolation and audit suites are
    │                          standing compliance controls, not ordinary tests.
    └── scripts/               Database role bootstrap for local development.
```

Documentation and code version together, deliberately: a spec change and the
code implementing it belong in one reviewable commit. That is what makes the
change-control process below workable rather than aspirational — and it is why
this set is markdown rather than PDF. Markdown diffs in a pull request; PDFs do
not.

---

## Conventions used across the set

- **Dates** are ISO or written in full. Never `03/04/26`.
- **Money** is INR with the symbol: ₹5,00,000. Indian digit grouping.
- **Entity names** are Title Case and match the SDD exactly — Candidate Profile, Application, Dispatch Record.
- **Event names** are PascalCase in backticks — `OfferSigned`, `KitDispatched`.
- **Field names** are `snake_case` in backticks.
- **`[OPEN]`** marks something genuinely undecided. **`[BLOCKED]`** marks something waiting on a named person. Neither is decorative — if you see one, it is real.
- **Module numbers** (Module 1–11) are stable across all documents and never renumbered, even if a module is descoped.

---

*Files live in `docs/`. Numbering is stable — a document is never renumbered, so links stay valid.*
