# app/cfo/db.py
"""
CFO Database Layer - Isolated from Core

All tables are org-isolated. This module provides data access
for CFO-specific tables that are separate from Core tier data.

CANONICAL LAWS:
- All queries include organization_id (org isolation)
- No cross-tier data access (CFO never reads core_transactions)
- Audit logging for mutations in router layer
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional
import os

from app.db import get_db_connection


# =============================================================================
# TABLE INITIALIZATION
# =============================================================================

def init_cfo_tables() -> None:
    """Create all CFO tables. Called from app startup."""
    migration_path = os.path.join(
        os.path.dirname(__file__),
        '../../migrations/003_cfo_isolation.sql'
    )

    with get_db_connection() as conn:
        if os.path.exists(migration_path):
            with open(migration_path, 'r') as f:
                conn.executescript(f.read())
        else:
            _create_tables_inline(conn)
        conn.commit()


def _create_tables_inline(conn) -> None:
    """Fallback table creation if migration file not found."""
    conn.executescript("""
        -- CFO Accounts
        CREATE TABLE IF NOT EXISTS cfo_accounts (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            account_name TEXT NOT NULL,
            account_type TEXT NOT NULL,
            institution_name TEXT,
            account_number_masked TEXT,
            currency TEXT DEFAULT 'USD',
            current_balance REAL DEFAULT 0,
            available_balance REAL,
            balance_as_of TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            created_by TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_cfo_accounts_org ON cfo_accounts(organization_id);

        -- CFO Transactions
        CREATE TABLE IF NOT EXISTS cfo_transactions (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            account_id TEXT,
            transaction_date TEXT NOT NULL,
            post_date TEXT,
            amount REAL NOT NULL,
            description TEXT,
            merchant_name TEXT,
            category TEXT,
            transaction_type TEXT,
            is_recurring INTEGER DEFAULT 0,
            recurring_frequency TEXT,
            department TEXT,
            cost_center TEXT,
            project_code TEXT,
            gl_code TEXT,
            status TEXT DEFAULT 'posted',
            reconciled_at TEXT,
            source TEXT DEFAULT 'manual',
            external_id TEXT,
            notes TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            created_by TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_cfo_tx_org ON cfo_transactions(organization_id);
        CREATE INDEX IF NOT EXISTS idx_cfo_tx_date ON cfo_transactions(organization_id, transaction_date DESC);
        CREATE INDEX IF NOT EXISTS idx_cfo_tx_account ON cfo_transactions(account_id);
        CREATE INDEX IF NOT EXISTS idx_cfo_tx_external ON cfo_transactions(organization_id, external_id);

        -- CFO Budgets
        CREATE TABLE IF NOT EXISTS cfo_budgets (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            name TEXT NOT NULL,
            period_type TEXT NOT NULL,
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            budgeted_revenue REAL DEFAULT 0,
            budgeted_expenses REAL DEFAULT 0,
            actual_revenue REAL DEFAULT 0,
            actual_expenses REAL DEFAULT 0,
            status TEXT DEFAULT 'active',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            created_by TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_cfo_budgets_org ON cfo_budgets(organization_id);

        -- CFO Budget Items
        CREATE TABLE IF NOT EXISTS cfo_budget_items (
            id TEXT PRIMARY KEY,
            budget_id TEXT NOT NULL,
            organization_id TEXT NOT NULL,
            category TEXT NOT NULL,
            department TEXT,
            budgeted_amount REAL NOT NULL,
            actual_amount REAL DEFAULT 0,
            notes TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_cfo_budget_items_budget ON cfo_budget_items(budget_id);

        -- CFO Snapshots
        CREATE TABLE IF NOT EXISTS cfo_snapshots (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            snapshot_date TEXT NOT NULL,
            metrics TEXT NOT NULL,
            insights TEXT,
            generated_at TEXT DEFAULT (datetime('now')),
            expires_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_cfo_snapshots_org ON cfo_snapshots(organization_id);
    """)


# =============================================================================
# GENERIC HELPERS
# =============================================================================

def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    """Convert sqlite3.Row to dict."""
    return dict(row)


def _fetch_one(query: str, params: tuple) -> Optional[Dict[str, Any]]:
    """Fetch a single row as dict."""
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(query, params).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def _fetch_all(query: str, params: tuple) -> List[Dict[str, Any]]:
    """Fetch all rows as list of dicts."""
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(query, params).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def _execute(query: str, params: tuple) -> None:
    """Execute a write query."""
    conn = get_db_connection()
    try:
        conn.execute(query, params)
        conn.commit()
    finally:
        conn.close()


# =============================================================================
# ACCOUNTS
# =============================================================================

def create_account(
    id: str,
    org_id: str,
    account_name: str,
    account_type: str,
    created_by: str,
    institution_name: Optional[str] = None,
    account_number_masked: Optional[str] = None,
    currency: str = "USD",
    current_balance: float = 0.0,
) -> None:
    """Create a new CFO account."""
    _execute(
        """INSERT INTO cfo_accounts
           (id, organization_id, account_name, account_type, institution_name,
            account_number_masked, currency, current_balance, created_by)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (id, org_id, account_name, account_type, institution_name,
         account_number_masked, currency, current_balance, created_by),
    )


def get_account(org_id: str, account_id: str) -> Optional[Dict[str, Any]]:
    """Get a single account by ID."""
    return _fetch_one(
        "SELECT * FROM cfo_accounts WHERE id = ? AND organization_id = ?",
        (account_id, org_id),
    )


def list_accounts(org_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    """List all accounts for an organization."""
    return _fetch_all(
        "SELECT * FROM cfo_accounts WHERE organization_id = ? AND is_active = 1 ORDER BY account_name LIMIT ?",
        (org_id, limit),
    )


def update_account(org_id: str, account_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Update an account."""
    allowed_fields = {'account_name', 'account_type', 'institution_name',
                      'account_number_masked', 'currency', 'current_balance',
                      'available_balance', 'balance_as_of', 'is_active'}
    sets = []
    vals = []
    for k, v in updates.items():
        if k in allowed_fields and v is not None:
            sets.append(f"{k} = ?")
            vals.append(v)
    if not sets:
        return get_account(org_id, account_id)
    sets.append("updated_at = datetime('now')")
    vals.extend([account_id, org_id])
    _execute(
        f"UPDATE cfo_accounts SET {', '.join(sets)} WHERE id = ? AND organization_id = ?",
        tuple(vals),
    )
    return get_account(org_id, account_id)


def delete_account(org_id: str, account_id: str) -> bool:
    """Soft delete an account."""
    _execute(
        "UPDATE cfo_accounts SET is_active = 0, updated_at = datetime('now') WHERE id = ? AND organization_id = ?",
        (account_id, org_id),
    )
    return True


# =============================================================================
# TRANSACTIONS
# =============================================================================

def create_transaction(
    id: str,
    org_id: str,
    transaction_date: str,
    amount: float,
    created_by: str,
    account_id: Optional[str] = None,
    description: Optional[str] = None,
    merchant_name: Optional[str] = None,
    category: Optional[str] = None,
    transaction_type: Optional[str] = None,
    department: Optional[str] = None,
    cost_center: Optional[str] = None,
    source: str = "manual",
    external_id: Optional[str] = None,
) -> None:
    """Create a new CFO transaction."""
    _execute(
        """INSERT INTO cfo_transactions
           (id, organization_id, account_id, transaction_date, amount, description,
            merchant_name, category, transaction_type, department, cost_center,
            source, external_id, created_by)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (id, org_id, account_id, transaction_date, amount, description,
         merchant_name, category, transaction_type, department, cost_center,
         source, external_id, created_by),
    )


def get_transaction(org_id: str, tx_id: str) -> Optional[Dict[str, Any]]:
    """Get a single transaction by ID."""
    return _fetch_one(
        "SELECT * FROM cfo_transactions WHERE id = ? AND organization_id = ?",
        (tx_id, org_id),
    )


def list_transactions(
    org_id: str,
    account_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """List transactions with optional filters."""
    conditions = ["organization_id = ?", "status != 'voided'"]
    params: list = [org_id]

    if account_id:
        conditions.append("account_id = ?")
        params.append(account_id)
    if start_date:
        conditions.append("transaction_date >= ?")
        params.append(start_date)
    if end_date:
        conditions.append("transaction_date <= ?")
        params.append(end_date)

    params.append(limit)

    return _fetch_all(
        f"""SELECT * FROM cfo_transactions
            WHERE {' AND '.join(conditions)}
            ORDER BY transaction_date DESC
            LIMIT ?""",
        tuple(params),
    )


def update_transaction(org_id: str, tx_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Update a transaction."""
    allowed_fields = {'amount', 'description', 'merchant_name', 'category',
                      'transaction_type', 'department', 'cost_center', 'status',
                      'notes', 'gl_code', 'project_code'}
    sets = []
    vals = []
    for k, v in updates.items():
        if k in allowed_fields:
            sets.append(f"{k} = ?")
            vals.append(v)
    if not sets:
        return get_transaction(org_id, tx_id)
    sets.append("updated_at = datetime('now')")
    vals.extend([tx_id, org_id])
    _execute(
        f"UPDATE cfo_transactions SET {', '.join(sets)} WHERE id = ? AND organization_id = ?",
        tuple(vals),
    )
    return get_transaction(org_id, tx_id)


def get_period_totals(
    org_id: str,
    start_date: str,
    end_date: str,
) -> Dict[str, float]:
    """Get revenue and expense totals for a period from CFO transactions."""
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    try:
        # Revenue: positive amounts
        cursor = conn.execute("""
            SELECT COALESCE(SUM(amount), 0) as total
            FROM cfo_transactions
            WHERE organization_id = ?
              AND transaction_date >= ? AND transaction_date <= ?
              AND amount > 0
              AND status != 'voided'
        """, (org_id, start_date, end_date))
        revenue = cursor.fetchone()[0] or 0.0

        # Expenses: negative amounts
        cursor = conn.execute("""
            SELECT COALESCE(SUM(ABS(amount)), 0) as total
            FROM cfo_transactions
            WHERE organization_id = ?
              AND transaction_date >= ? AND transaction_date <= ?
              AND amount < 0
              AND status != 'voided'
        """, (org_id, start_date, end_date))
        expenses = cursor.fetchone()[0] or 0.0

        return {
            "revenue": revenue,
            "expenses": expenses,
            "net": revenue - expenses
        }
    finally:
        conn.close()


def get_cash_balance(org_id: str, as_of_date: str) -> float:
    """Get total cash balance as of a specific date."""
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute("""
            SELECT COALESCE(SUM(amount), 0) as balance
            FROM cfo_transactions
            WHERE organization_id = ?
              AND transaction_date <= ?
              AND status != 'voided'
        """, (org_id, as_of_date))
        return cursor.fetchone()[0] or 0.0
    finally:
        conn.close()


def bulk_import_transactions(
    org_id: str,
    transactions: List[Dict[str, Any]],
    created_by: str,
) -> Dict[str, int]:
    """Bulk import transactions from CSV."""
    import uuid
    conn = get_db_connection()
    imported = 0
    skipped = 0

    try:
        for tx in transactions:
            # Check for duplicate via external_id
            if tx.get("external_id"):
                existing = conn.execute(
                    "SELECT id FROM cfo_transactions WHERE organization_id = ? AND external_id = ?",
                    (org_id, tx["external_id"])
                ).fetchone()
                if existing:
                    skipped += 1
                    continue

            tx_id = str(uuid.uuid4())

            conn.execute(
                """INSERT INTO cfo_transactions
                   (id, organization_id, account_id, transaction_date, amount, description,
                    merchant_name, category, transaction_type, department, cost_center,
                    source, external_id, created_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'csv_import', ?, ?)""",
                (
                    tx_id, org_id, tx.get("account_id"), tx["transaction_date"],
                    tx["amount"], tx.get("description"), tx.get("merchant_name"),
                    tx.get("category"), tx.get("transaction_type"), tx.get("department"),
                    tx.get("cost_center"), tx.get("external_id"), created_by
                ),
            )
            imported += 1

        conn.commit()
        return {"imported": imported, "skipped": skipped}
    finally:
        conn.close()


# =============================================================================
# AGGREGATIONS (for CFO overview)
# =============================================================================

def get_top_revenue_sources(
    org_id: str,
    start_date: str,
    end_date: str,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """Get top revenue sources for CFO overview."""
    return _fetch_all(
        """SELECT
            COALESCE(merchant_name, category, 'Other') as source,
            COUNT(*) as transaction_count,
            COALESCE(SUM(amount), 0) as total
        FROM cfo_transactions
        WHERE organization_id = ?
          AND transaction_date >= ? AND transaction_date <= ?
          AND amount > 0
          AND status != 'voided'
        GROUP BY source
        ORDER BY total DESC
        LIMIT ?""",
        (org_id, start_date, end_date, limit),
    )


def get_top_expense_categories(
    org_id: str,
    start_date: str,
    end_date: str,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """Get top expense categories for CFO overview."""
    return _fetch_all(
        """SELECT
            COALESCE(category, merchant_name, 'Other') as category,
            COUNT(*) as transaction_count,
            COALESCE(SUM(ABS(amount)), 0) as total
        FROM cfo_transactions
        WHERE organization_id = ?
          AND transaction_date >= ? AND transaction_date <= ?
          AND amount < 0
          AND status != 'voided'
        GROUP BY category
        ORDER BY total DESC
        LIMIT ?""",
        (org_id, start_date, end_date, limit),
    )
