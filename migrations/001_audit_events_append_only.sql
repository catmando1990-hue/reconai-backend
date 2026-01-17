-- Migration: Append-only audit events table (Postgres/Supabase)
-- Purpose: DCAA-compliant immutable audit trail with hash chaining
-- Retention: 6 years per FAR requirements
--
-- IMPORTANT: This table is APPEND-ONLY. No UPDATE/DELETE operations are permitted.
-- The application role should have INSERT and SELECT only.

CREATE TABLE IF NOT EXISTS audit_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  actor_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT,
  payload JSONB NOT NULL,
  prev_hash TEXT,
  event_hash TEXT NOT NULL
);

-- Hard immutability: application role must not be able to UPDATE/DELETE.
-- This revokes from PUBLIC; specific roles can be granted INSERT/SELECT as needed.
REVOKE UPDATE, DELETE ON audit_events FROM PUBLIC;

-- Indexes for query performance
CREATE INDEX IF NOT EXISTS idx_audit_events_created_at ON audit_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_events_entity ON audit_events(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_events_actor ON audit_events(actor_id);
CREATE INDEX IF NOT EXISTS idx_audit_events_type ON audit_events(event_type);

-- For Supabase: Enable RLS if exposing via PostgREST
-- ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;
-- CREATE POLICY "Allow insert from service role only" ON audit_events
--   FOR INSERT TO service_role WITH CHECK (true);
-- CREATE POLICY "Allow select for authenticated users" ON audit_events
--   FOR SELECT TO authenticated USING (true);

COMMENT ON TABLE audit_events IS 'Append-only audit trail for DCAA compliance. No UPDATE/DELETE permitted. Hash chain ensures tamper-evidence.';
COMMENT ON COLUMN audit_events.prev_hash IS 'Hash of the previous event for chain integrity verification';
COMMENT ON COLUMN audit_events.event_hash IS 'SHA-256 hash of this event (optionally HMAC with AUDIT_HASH_SECRET)';
