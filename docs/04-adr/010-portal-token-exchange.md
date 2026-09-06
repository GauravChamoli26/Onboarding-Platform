# ADR-010: Candidate portal token exchanged on first use

**Status:** Accepted
**Date:** 2026-08-30
**Decision Log ref:** B-01

## Context

Candidates have no accounts by design — no SSO, no password. Access is an expiring link scoped to a single Application, delivered by email.

That link is an unauthenticated bearer credential. Bearer credentials in URLs leak in predictable ways: forwarded emails, browser history, shared screenshots, server access logs, analytics, and `Referer` headers sent to any embedded third party. The Digio signing widget is embedded in exactly these pages.

The naive design transmits the token on every request for the life of the link.

## Decision

The link token is **single-use for exchange**. On first use it is swapped for a short-lived, `HttpOnly`, `SameSite=Lax` session cookie scoped to that Application.

Supporting controls:

- Token in the URL **path**, never the query string
- `Referrer-Policy: no-referrer` on all portal pages
- Hashed at rest with constant-time comparison; the raw token is never stored
- Purpose-scoped: a document-upload link cannot sign an offer
- Revoked automatically when the Application reaches a terminal state, regardless of expiry
- Rate-limited per token and per IP, with alerting above threshold

## Consequences

The token crosses the wire once. Everything after that is a standard session cookie with standard protections.

Candidates who open a link on one device and continue on another must request a fresh link. That is a small usability cost and the right trade for a credential protecting Aadhaar and PAN documents.

Every notification that contains a portal link records which token it issued, so a leak can be traced to its delivery.

## Alternatives considered

**Long-lived token in the URL, used on every request** — simplest, and the common implementation. Rejected: it maximises exposure of the one credential protecting the most sensitive data in the system.

**Magic-link with OTP confirmation** — stronger, but adds friction to a flow candidates already find tedious, and the population includes users who will struggle with it.
