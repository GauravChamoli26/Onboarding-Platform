-- ============================================================================
-- init-db.sql — database role bootstrap
-- ----------------------------------------------------------------------------
-- WHAT THIS DOES
--   Creates the non-superuser role the application connects as.
--
-- WHY THIS IS NOT A MIGRATION
--   Role creation is an infrastructure concern, not a schema concern. In real
--   environments Terraform creates this role and stores the password in Secrets
--   Manager (ADR-009, ADR-014). This file exists so local development matches
--   that shape rather than running everything as superuser and accidentally
--   bypassing row-level security.
--
-- THE CRITICAL POINT
--   PostgreSQL exempts superusers and table owners from RLS policies unless
--   FORCE ROW LEVEL SECURITY is set. If the application connected as the table
--   owner, every tenant policy would silently do nothing — and the isolation
--   tests would still pass, in a way that means nothing. Hence a separate,
--   deliberately unprivileged role. See ADR-002.
-- ============================================================================

-- The application role. No superuser, no createdb, no createrole.
CREATE ROLE app_user WITH LOGIN PASSWORD 'app_password';

GRANT CONNECT ON DATABASE onboarding TO app_user;
GRANT USAGE ON SCHEMA public TO app_user;

-- Grant on everything that exists now AND everything created later by the
-- migration role. Without the ALTER DEFAULT PRIVILEGES line, every new
-- migration would silently create tables the application cannot read.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_user;

-- NOTE: no UPDATE or DELETE grant will be given on the audit log table when it
-- is created in Phase 1. That is how ADR-016 enforces append-only.
