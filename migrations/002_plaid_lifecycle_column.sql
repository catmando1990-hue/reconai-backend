-- Migration 002: Add lifecycle column to plaid_items
-- This column stores the canonical lifecycle state for Plaid items
-- 
-- Lifecycle States:
--   created       - Item record exists, token exchanged, initial sync not started
--   pending       - Initial sync in progress (transactions not yet available)
--   processing    - Async product data being prepared by Plaid
--   ready         - All requested products are available and synced
--   login_required - User must re-authenticate via Plaid Link
--   error         - Unrecoverable error state (requires manual intervention)
--
-- The legacy 'status' column is preserved for backward compatibility.
-- New code should use 'lifecycle' column exclusively.

-- Add lifecycle column with default 'created'
ALTER TABLE plaid_items ADD COLUMN lifecycle TEXT DEFAULT 'created';

-- Migrate existing status values to lifecycle
UPDATE plaid_items SET lifecycle = CASE
    WHEN status = 'active' THEN 'ready'
    WHEN status = 'pending' THEN 'pending'
    WHEN status = 'login_required' THEN 'login_required'
    WHEN status = 'error' THEN 'error'
    WHEN status = 'disconnected' THEN 'error'
    ELSE 'created'
END WHERE lifecycle IS NULL OR lifecycle = 'created';

-- Create index for lifecycle queries
CREATE INDEX IF NOT EXISTS idx_plaid_items_lifecycle ON plaid_items(lifecycle);
