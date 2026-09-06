# ADR-001: Python, FastAPI and the core application stack

**Status:** Accepted
**Date:** 2026-08-30
**Decision Log ref:** A-01

## Context

The platform's hardest technical work is LLM orchestration (JD generation, resume parsing, scoring, Copilot) and document processing (PDF and DOCX extraction, OCR for scanned resumes). The team is fluent in Python and has very little Java or equivalent. The build is roughly nine months of sustained work, so language choice compounds.

## Decision

Python 3.12 with FastAPI for services, SQLAlchemy 2.0 for the data layer, Alembic for migrations, and Pydantic v2 as the single schema layer.

Pydantic carries more weight here than in a typical service: it validates API requests and responses, the domain event envelope at both emit and consume, structured LLM output, and vendor webhook payloads. Four boundaries, one schema mechanism.

FastAPI is async-native, which matters because vendor webhooks and LLM calls dominate the I/O profile, and it generates the OpenAPI spec that contract tests run against.

## Consequences

The team can move at full speed from day one, and every backend hire draws from a large pool.

SQLAlchemy over the Django ORM means no admin scaffolding — we build our own internal screens. That is a real cost, several weeks across the project, accepted because the constraints and triggers in SDD §1.13 need explicit control that the Django ORM makes awkward.

Nothing in this stack helps with the browser. See ADR-007.

## Alternatives considered

**Django + DRF** — better scaffolding and a mature admin, but a weaker async story and heavier ORM coupling. The admin would have saved time; the async and RLS control mattered more.

**Node/TypeScript** — would unify with the frontend and remove a language boundary. Rejected because it discards the team's strongest skill and has a weaker ecosystem for exactly the document-processing work that is hardest here.
