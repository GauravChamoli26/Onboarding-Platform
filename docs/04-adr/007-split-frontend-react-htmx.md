# ADR-007: React for the internal app, HTMX for the candidate portal

**Status:** Accepted
**Date:** 2026-08-30
**Decision Log ref:** A-04, A-05

## Context

Two frontend surfaces with genuinely different requirements.

The **internal application** — HR, Hiring Manager, Interviewer, Admin — needs pipeline views, a Candidate 360 timeline, scheduling interfaces, approvals queues and dashboards. Rich, stateful, heavily interactive.

The **candidate portal** is six screens: status, document upload, reschedule request, offer review and signing, withdrawal, consent management. Token-authenticated, no accounts, no persistent client state. Its users are candidates in India, many on low-end Android devices over patchy connections.

The team is Python-heavy.

## Decision

**Internal application:** React 18 + TypeScript + Vite, with shadcn/ui and Tailwind, TanStack Query for server state, React Hook Form and Zod for forms, TanStack Table for the pipeline and reporting views.

**Candidate portal:** server-rendered Jinja2 with HTMX, served by FastAPI.

## Consequences

The portal stays in Python, so the whole team can maintain it. Its payload is a fraction of an SPA's, which matters for the users we are actually trying to reach. And the token-validation boundary stays on the server, with no client-side auth logic to get wrong — the portal is the platform's weakest security surface, and server rendering removes a class of mistakes from it.

The cost is two frontend paradigms in one codebase. That is a real cost and the main argument against this split.

React capability is needed from Phase 2, and it is the one skill the rest of the stack does not supply. The internal SPA is not a weekend for a backend engineer.

## Alternatives considered

**React for both** — one paradigm, simpler hiring, and a defensible choice. Rejected because the portal is small, security-sensitive and performance-sensitive for low-end devices, which is precisely where server rendering wins.

**HTMX for both** — would keep everything in Python. Rejected because the internal pipeline and dashboard views need genuine client-side state management.
