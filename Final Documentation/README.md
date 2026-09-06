# 04 — Architecture Decision Records

One file per decision. Format is Nygard-standard: Context, Decision, Consequences.

**Status values:** `Accepted` · `Superseded by ADR-NNN` · `Deprecated` · `Proposed`

**Adding an ADR:** copy `TEMPLATE.md`, take the next number, never reuse or renumber. An ADR is never edited after acceptance — to change a decision, write a new ADR that supersedes it and update the old one's status line only.

| ADR | Title | Status |
|---|---|---|
| [001](001-python-fastapi-stack.md) | Python, FastAPI and the core application stack | Accepted |
| [002](002-postgresql-row-level-security.md) | PostgreSQL with row-level security for multi-tenancy | Accepted |
| [003](003-modular-monolith.md) | Modular monolith over microservices | Accepted |
| [004](004-transactional-outbox-eventbridge.md) | Transactional outbox to EventBridge to per-consumer SQS | Accepted |
| [005](005-postgres-fts-no-opensearch.md) | PostgreSQL full-text search, no dedicated search cluster | Accepted |
| [006](006-direct-saml-oidc-implementation.md) | Direct SAML/OIDC service provider implementation | Accepted |
| [007](007-split-frontend-react-htmx.md) | React for the internal app, HTMX for the candidate portal | Accepted |
| [008](008-no-llm-orchestration-framework.md) | No LLM orchestration framework | Accepted |
| [009](009-terraform-in-region-state.md) | Terraform with a self-managed in-region state backend | Accepted |
| [010](010-portal-token-exchange.md) | Candidate portal token exchanged on first use | Accepted |
| [011](011-llm-output-has-no-authority.md) | LLM output has no authority over state or authorisation | Accepted |
| [012](012-immutable-config-versions.md) | Immutable version rows for versioned configuration | Accepted |
| [013](013-employment-record-handoff.md) | Hand off employment records rather than retain them | Accepted |
| [014](014-residency-fail-closed.md) | Residency enforced by fail-closed adapters | Accepted |
| [015](015-vendor-adapter-boundary.md) | Every integration behind an adapter interface | Accepted |
| [016](016-hash-chained-audit-log.md) | Append-only hash-chained audit log | Accepted |
