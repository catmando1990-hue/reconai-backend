-- =============================================================================
-- TIER-SPECIFIC BANK CONNECTIONS SCHEMA
-- Migration: 004_tier_connections.sql
-- Purpose: Separate connection tables for each paid tier (CFO, Payroll, GovCon)
-- =============================================================================

-- =============================================================================
-- CFO TIER CONNECTIONS
-- Supports both Plaid and manual entry
-- =============================================================================

CREATE TABLE IF NOT EXISTS cfo_connections (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,

    -- Connection type: 'plaid' or 'manual'
    connection_type TEXT NOT NULL CHECK (connection_type IN ('plaid', 'manual')),

    -- Plaid-specific (NULL for manual)
    plaid_item_id TEXT,
    plaid_access_token TEXT,
    plaid_institution_id TEXT,
    plaid_institution_name TEXT,

    -- Manual-specific / shared fields
    institution_name TEXT,
    account_name TEXT,
    account_type TEXT,
    account_mask TEXT,

    -- Status
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'error')),
    last_synced_at TEXT,
    error_message TEXT,

    -- Metadata
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    created_by TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cfo_connections_org ON cfo_connections(organization_id);
CREATE INDEX IF NOT EXISTS idx_cfo_connections_status ON cfo_connections(organization_id, status);


-- =============================================================================
-- PAYROLL TIER CONNECTIONS
-- Supports both Plaid and manual entry with payroll-specific fields
-- =============================================================================

CREATE TABLE IF NOT EXISTS payroll_connections (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,

    -- Connection type: 'plaid' or 'manual'
    connection_type TEXT NOT NULL CHECK (connection_type IN ('plaid', 'manual')),

    -- Plaid-specific (NULL for manual)
    plaid_item_id TEXT,
    plaid_access_token TEXT,
    plaid_institution_id TEXT,
    plaid_institution_name TEXT,

    -- Manual-specific / shared fields
    institution_name TEXT,
    account_name TEXT,
    account_type TEXT CHECK (account_type IN ('checking', 'savings', 'payroll')),
    account_mask TEXT,

    -- Payroll-specific: designated purpose
    purpose TEXT CHECK (purpose IN ('payroll_funding', 'tax_payments', 'benefits', 'general')),

    -- Status
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'error')),
    last_synced_at TEXT,
    error_message TEXT,

    -- Metadata
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    created_by TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_payroll_connections_org ON payroll_connections(organization_id);
CREATE INDEX IF NOT EXISTS idx_payroll_connections_status ON payroll_connections(organization_id, status);
CREATE INDEX IF NOT EXISTS idx_payroll_connections_purpose ON payroll_connections(organization_id, purpose);


-- =============================================================================
-- GOVCON TIER CONNECTIONS (Manual Only - DCAA Compliance)
-- Manual entry only for audit trail requirements
-- =============================================================================

CREATE TABLE IF NOT EXISTS govcon_connections (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,

    -- GovCon is manual-only for DCAA compliance
    connection_type TEXT NOT NULL DEFAULT 'manual' CHECK (connection_type = 'manual'),

    -- Institution details (manually entered)
    institution_name TEXT NOT NULL,
    account_name TEXT NOT NULL,
    account_type TEXT NOT NULL CHECK (account_type IN ('checking', 'savings', 'trust', 'escrow')),
    account_number_masked TEXT, -- Last 4 digits only
    routing_number_masked TEXT, -- Last 4 digits only

    -- GovCon-specific: contract association
    contract_id TEXT, -- Optional: link to specific contract
    cost_pool TEXT CHECK (cost_pool IN ('direct', 'indirect', 'overhead', 'g_and_a', 'fringe')),

    -- DCAA compliance fields
    authorization_date TEXT, -- Date account was authorized for use
    authorized_by TEXT, -- Who authorized this account
    evidence_document_id TEXT, -- Link to uploaded authorization doc

    -- Status
    status TEXT NOT NULL DEFAULT 'pending_verification' CHECK (status IN ('pending_verification', 'verified', 'inactive', 'rejected')),
    verified_at TEXT,
    verified_by TEXT,

    -- Metadata
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    created_by TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_govcon_connections_org ON govcon_connections(organization_id);
CREATE INDEX IF NOT EXISTS idx_govcon_connections_contract ON govcon_connections(contract_id);
CREATE INDEX IF NOT EXISTS idx_govcon_connections_status ON govcon_connections(organization_id, status);
CREATE INDEX IF NOT EXISTS idx_govcon_connections_cost_pool ON govcon_connections(organization_id, cost_pool);
