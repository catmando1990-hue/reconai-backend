-- ============================================================
-- CFO DATA ISOLATION SCHEMA
-- Migration: 003_cfo_isolation.sql
-- Purpose: Creates separate data silo for CFO tier
-- ============================================================

-- CFO Accounts (manual entry or separate integration)
CREATE TABLE IF NOT EXISTS cfo_accounts (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,

    -- Account details
    account_name TEXT NOT NULL,
    account_type TEXT NOT NULL CHECK (account_type IN ('bank', 'credit', 'investment', 'loan', 'other')),
    institution_name TEXT,
    account_number_masked TEXT,
    currency TEXT DEFAULT 'USD',

    -- Current state
    current_balance REAL DEFAULT 0,
    available_balance REAL,
    balance_as_of TEXT,

    -- Metadata
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    created_by TEXT NOT NULL,

    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_cfo_accounts_org ON cfo_accounts(organization_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_cfo_accounts_org_name ON cfo_accounts(organization_id, account_name);

-- CFO Transactions (manual entry or CSV import)
CREATE TABLE IF NOT EXISTS cfo_transactions (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    account_id TEXT,

    -- Transaction details
    transaction_date TEXT NOT NULL,
    post_date TEXT,
    amount REAL NOT NULL,
    description TEXT,
    merchant_name TEXT,
    category TEXT,

    -- Classification
    transaction_type TEXT CHECK (transaction_type IN ('revenue', 'expense', 'transfer', 'other')),
    is_recurring INTEGER DEFAULT 0,
    recurring_frequency TEXT,

    -- CFO-specific fields
    department TEXT,
    cost_center TEXT,
    project_code TEXT,
    gl_code TEXT,

    -- Status
    status TEXT DEFAULT 'posted' CHECK (status IN ('pending', 'posted', 'reconciled', 'voided')),
    reconciled_at TEXT,

    -- Source tracking
    source TEXT DEFAULT 'manual' CHECK (source IN ('manual', 'csv_import', 'api_sync')),
    external_id TEXT,
    notes TEXT,

    -- Metadata
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    created_by TEXT NOT NULL,

    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    FOREIGN KEY (account_id) REFERENCES cfo_accounts(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_cfo_tx_org ON cfo_transactions(organization_id);
CREATE INDEX IF NOT EXISTS idx_cfo_tx_date ON cfo_transactions(organization_id, transaction_date DESC);
CREATE INDEX IF NOT EXISTS idx_cfo_tx_account ON cfo_transactions(account_id);
CREATE INDEX IF NOT EXISTS idx_cfo_tx_external ON cfo_transactions(organization_id, external_id);

-- CFO Budgets
CREATE TABLE IF NOT EXISTS cfo_budgets (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,

    -- Budget details
    name TEXT NOT NULL,
    period_type TEXT NOT NULL CHECK (period_type IN ('monthly', 'quarterly', 'annual')),
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,

    -- Amounts
    budgeted_revenue REAL DEFAULT 0,
    budgeted_expenses REAL DEFAULT 0,

    -- Actuals (computed or cached)
    actual_revenue REAL DEFAULT 0,
    actual_expenses REAL DEFAULT 0,

    -- Status
    status TEXT DEFAULT 'active' CHECK (status IN ('draft', 'active', 'closed')),

    -- Metadata
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    created_by TEXT NOT NULL,

    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_cfo_budgets_org ON cfo_budgets(organization_id);

-- CFO Budget Line Items
CREATE TABLE IF NOT EXISTS cfo_budget_items (
    id TEXT PRIMARY KEY,
    budget_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,

    -- Line item details
    category TEXT NOT NULL,
    department TEXT,

    -- Amounts
    budgeted_amount REAL NOT NULL,
    actual_amount REAL DEFAULT 0,

    -- Metadata
    notes TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),

    FOREIGN KEY (budget_id) REFERENCES cfo_budgets(id) ON DELETE CASCADE,
    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_cfo_budget_items_budget ON cfo_budget_items(budget_id);

-- CFO Snapshots (cached executive summaries)
CREATE TABLE IF NOT EXISTS cfo_snapshots (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,

    -- Snapshot data
    snapshot_date TEXT NOT NULL,
    metrics TEXT NOT NULL,  -- JSON blob
    insights TEXT,          -- JSON blob (AI-generated)

    -- Metadata
    generated_at TEXT DEFAULT (datetime('now')),
    expires_at TEXT,

    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_cfo_snapshots_org ON cfo_snapshots(organization_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_cfo_snapshots_daily ON cfo_snapshots(organization_id, snapshot_date);
