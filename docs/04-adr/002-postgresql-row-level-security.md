# ADR-002: PostgreSQL with row-level security for multi-tenancy

**Status:** Accepted
**Date:** 2026-08-30
**Decision Log ref:** A-02

## Context

The platform is multi-entity by design — one deployment serves multiple hiring organisations, each holding Aadhaar, PAN and EPFO details of candidates. Cross-tenant data leakage is the single worst failure mode available to this system: it is a DPDP breach, a customer-terminating event, and unrecoverable in reputation terms.

Application-layer scoping means every query must remember to filter by `organization_id`. Across a nine-month build and hundreds of endpoints, some query will forget.

## Decision

PostgreSQL 16 with row-level security as the enforcement mechanism. The tenant is set per connection from the authenticated session. `organization_id` is present on every entity without exception, including child records, so isolation is enforceable at one layer rather than inferred through joins.

An application-layer guard sits on top as defence in depth, but RLS is the boundary that holds.

A two-tenant isolation suite runs on every pull request from week 2 and never comes out. Every integration test executes with two organisations present and asserts zero cross-tenant visibility.

## Consequences

Application code cannot issue an unscoped query even by accident. That is the entire point.

RLS has a query planning cost, and policies must be written carefully or they silently degrade performance at scale. At 500–1,000 applications per month this is not a concern for years.

Testing requires a real PostgreSQL instance — RLS and triggers cannot be tested against SQLite. Hence `testcontainers` in the test stack.

Connection pooling needs care: the tenant context must be set and reset per checkout, or a pooled connection can carry the previous tenant's context. This is a known footgun and is covered by the isolation suite.

## Alternatives considered

**Application-layer scoping only** — simpler, and what most teams do. Rejected because it relies on discipline at every call site, and the failure is silent.

**Database per tenant** — strongest isolation, but migration and operational overhead scale with customer count, and cross-tenant analytics become painful.

**MySQL** — no row-level security, weaker JSON support.
