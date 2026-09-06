# ADR-005: PostgreSQL full-text search, no dedicated search cluster

**Status:** Accepted
**Date:** 2026-08-30
**Decision Log ref:** A-08

## Context

Module 10 requires the Talent Pool to be searchable by skills, past role and score history. The reflex is to provision OpenSearch.

At 500–1,000 applications per month, the corpus is 6,000–12,000 profiles per year.

## Decision

PostgreSQL full-text search with `pg_trgm` for fuzzy matching. No search cluster.

Revisit at roughly 500,000 profiles, or if semantic rather than keyword search becomes a product requirement.

## Consequences

One less system to operate, secure, back up and pay for.

More importantly: one less system in the purge path. The retention job must destroy candidate data completely, and a second datastore means deleting from two systems and proving both succeeded. That is exactly the kind of complexity that produces a compliance gap nobody notices until an audit.

The cost is that search relevance will be cruder than a purpose-built engine, and complex faceted search will be slower to build. At this corpus size neither is noticeable.

## Alternatives considered

**OpenSearch from day one** — better relevance, and a defensible choice at ten times the volume. Rejected as premature, primarily on the purge-path argument rather than the cost one.

**pgvector for semantic matching** — genuinely interesting for talent-pool matching later, and available in the same database when wanted. Not needed for keyword search.
