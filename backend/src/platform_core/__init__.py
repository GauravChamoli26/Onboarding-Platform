"""
platform_core - the shared kernel.

Everything in this package is used by every functional module. Nothing here
knows about jobs, candidates, offers or any other domain concept; if it does,
it belongs in src/modules/ instead.

Layout (SDD 3.0):
    config/    application settings, environment-backed
    db/        engine, session handling, base model conventions
    tenancy/   the tenant context that drives row-level security

Phase 1 adds: auth/, events/, audit/, approvals/, notifications/, sla/
"""
