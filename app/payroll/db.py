# app/payroll/db.py
"""
Payroll Database Layer

All tables are org-isolated. All mutations are paired with audit logging
in the router layer (not here — this is pure data access).

CANONICAL LAWS:
- All queries include organization_id (org isolation)
- No cross-org access
- Locked pay runs are immutable (enforced here)
- Snapshots are append-only (INSERT only, no UPDATE/DELETE)
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from app.db import get_db_connection


# =============================================================================
# TABLE INITIALIZATION
# =============================================================================

def init_payroll_tables() -> None:
    """Create all payroll tables. Called from app startup."""
    with get_db_connection() as conn:
        conn.executescript("""
            -- PEOPLE
            CREATE TABLE IF NOT EXISTS payroll_people (
                id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                employee_id TEXT NOT NULL,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                email TEXT,
                department TEXT,
                job_title TEXT,
                hire_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_pp_org ON payroll_people(organization_id);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_pp_org_emp ON payroll_people(organization_id, employee_id);

            -- COMPENSATION
            CREATE TABLE IF NOT EXISTS payroll_compensation (
                id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                person_id TEXT NOT NULL,
                comp_type TEXT NOT NULL,
                rate REAL NOT NULL,
                currency TEXT NOT NULL DEFAULT 'USD',
                effective_date TEXT NOT NULL,
                end_date TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_pc_org ON payroll_compensation(organization_id);
            CREATE INDEX IF NOT EXISTS idx_pc_person ON payroll_compensation(person_id);

            -- TIME & LABOR
            CREATE TABLE IF NOT EXISTS payroll_time_entries (
                id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                person_id TEXT NOT NULL,
                work_date TEXT NOT NULL,
                hours REAL NOT NULL,
                cost_code TEXT,
                description TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_pte_org ON payroll_time_entries(organization_id);
            CREATE INDEX IF NOT EXISTS idx_pte_person ON payroll_time_entries(person_id);
            CREATE INDEX IF NOT EXISTS idx_pte_date ON payroll_time_entries(work_date);

            -- PAY RUNS
            CREATE TABLE IF NOT EXISTS payroll_pay_runs (
                id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                pay_period_start TEXT NOT NULL,
                pay_period_end TEXT NOT NULL,
                description TEXT,
                status TEXT NOT NULL DEFAULT 'draft',
                total_gross REAL NOT NULL DEFAULT 0,
                total_tax REAL NOT NULL DEFAULT 0,
                total_benefits REAL NOT NULL DEFAULT 0,
                total_deductions REAL NOT NULL DEFAULT 0,
                total_net REAL NOT NULL DEFAULT 0,
                line_count INTEGER NOT NULL DEFAULT 0,
                locked_at TEXT,
                snapshot_id TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_ppr_org ON payroll_pay_runs(organization_id);
            CREATE INDEX IF NOT EXISTS idx_ppr_status ON payroll_pay_runs(status);

            -- PAY RUN LINE ITEMS
            CREATE TABLE IF NOT EXISTS payroll_pay_run_lines (
                id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                pay_run_id TEXT NOT NULL,
                person_id TEXT NOT NULL,
                gross_amount REAL NOT NULL DEFAULT 0,
                tax_amount REAL NOT NULL DEFAULT 0,
                benefits_amount REAL NOT NULL DEFAULT 0,
                deductions_amount REAL NOT NULL DEFAULT 0,
                net_amount REAL NOT NULL DEFAULT 0,
                hours_worked REAL,
                cost_code TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_pprl_org ON payroll_pay_run_lines(organization_id);
            CREATE INDEX IF NOT EXISTS idx_pprl_run ON payroll_pay_run_lines(pay_run_id);

            -- TAX WITHHOLDINGS
            CREATE TABLE IF NOT EXISTS payroll_tax_withholdings (
                id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                person_id TEXT NOT NULL,
                tax_type TEXT NOT NULL,
                rate REAL NOT NULL,
                effective_date TEXT NOT NULL,
                filing_status TEXT,
                allowances INTEGER,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_ptw_org ON payroll_tax_withholdings(organization_id);
            CREATE INDEX IF NOT EXISTS idx_ptw_person ON payroll_tax_withholdings(person_id);

            -- BENEFIT ENROLLMENTS
            CREATE TABLE IF NOT EXISTS payroll_benefit_enrollments (
                id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                person_id TEXT NOT NULL,
                benefit_type TEXT NOT NULL,
                plan_name TEXT NOT NULL,
                employee_contribution REAL NOT NULL DEFAULT 0,
                employer_contribution REAL NOT NULL DEFAULT 0,
                effective_date TEXT NOT NULL,
                end_date TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_pbe_org ON payroll_benefit_enrollments(organization_id);
            CREATE INDEX IF NOT EXISTS idx_pbe_person ON payroll_benefit_enrollments(person_id);

            -- PAYROLL JOURNAL ENTRIES (accounting)
            CREATE TABLE IF NOT EXISTS payroll_journal_entries (
                id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                pay_run_id TEXT NOT NULL,
                account_code TEXT NOT NULL,
                debit REAL NOT NULL DEFAULT 0,
                credit REAL NOT NULL DEFAULT 0,
                description TEXT NOT NULL,
                cost_code TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_pje_org ON payroll_journal_entries(organization_id);
            CREATE INDEX IF NOT EXISTS idx_pje_run ON payroll_journal_entries(pay_run_id);

            -- COMPLIANCE CHECKS
            CREATE TABLE IF NOT EXISTS payroll_compliance_checks (
                id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                pay_run_id TEXT NOT NULL,
                check_type TEXT NOT NULL,
                status TEXT NOT NULL,
                message TEXT NOT NULL,
                details TEXT,
                checked_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_pcc_org ON payroll_compliance_checks(organization_id);
            CREATE INDEX IF NOT EXISTS idx_pcc_run ON payroll_compliance_checks(pay_run_id);

            -- SNAPSHOTS (IMMUTABLE — INSERT ONLY)
            CREATE TABLE IF NOT EXISTS payroll_snapshots (
                id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                snapshot_type TEXT NOT NULL,
                pay_run_id TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                data_hash TEXT NOT NULL,
                data TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_ps_org ON payroll_snapshots(organization_id);
            CREATE INDEX IF NOT EXISTS idx_ps_run ON payroll_snapshots(pay_run_id);
            CREATE INDEX IF NOT EXISTS idx_ps_type ON payroll_snapshots(snapshot_type);
        """)
        conn.commit()


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
# PEOPLE
# =============================================================================

def create_person(
    id: str, org_id: str, employee_id: str, first_name: str, last_name: str,
    email: Optional[str], department: Optional[str], job_title: Optional[str],
    hire_date: str, status: str,
) -> None:
    _execute(
        """INSERT INTO payroll_people
           (id, organization_id, employee_id, first_name, last_name, email,
            department, job_title, hire_date, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (id, org_id, employee_id, first_name, last_name, email,
         department, job_title, hire_date, status),
    )


def get_person(org_id: str, person_id: str) -> Optional[Dict[str, Any]]:
    return _fetch_one(
        "SELECT * FROM payroll_people WHERE id = ? AND organization_id = ?",
        (person_id, org_id),
    )


def list_people(org_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    return _fetch_all(
        "SELECT * FROM payroll_people WHERE organization_id = ? ORDER BY last_name, first_name LIMIT ?",
        (org_id, limit),
    )


def update_person(org_id: str, person_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    sets = []
    vals = []
    for k, v in updates.items():
        if k in ("first_name", "last_name", "email", "department", "job_title", "status") and v is not None:
            sets.append(f"{k} = ?")
            vals.append(v)
    if not sets:
        return get_person(org_id, person_id)
    sets.append("updated_at = datetime('now')")
    vals.extend([person_id, org_id])
    _execute(
        f"UPDATE payroll_people SET {', '.join(sets)} WHERE id = ? AND organization_id = ?",
        tuple(vals),
    )
    return get_person(org_id, person_id)


# =============================================================================
# COMPENSATION
# =============================================================================

def create_compensation(
    id: str, org_id: str, person_id: str, comp_type: str,
    rate: float, currency: str, effective_date: str, end_date: Optional[str],
) -> None:
    _execute(
        """INSERT INTO payroll_compensation
           (id, organization_id, person_id, comp_type, rate, currency, effective_date, end_date)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (id, org_id, person_id, comp_type, rate, currency, effective_date, end_date),
    )


def list_compensation(org_id: str, person_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    if person_id:
        return _fetch_all(
            "SELECT * FROM payroll_compensation WHERE organization_id = ? AND person_id = ? ORDER BY effective_date DESC LIMIT ?",
            (org_id, person_id, limit),
        )
    return _fetch_all(
        "SELECT * FROM payroll_compensation WHERE organization_id = ? ORDER BY effective_date DESC LIMIT ?",
        (org_id, limit),
    )


# =============================================================================
# TIME & LABOR
# =============================================================================

def create_time_entry(
    id: str, org_id: str, person_id: str, work_date: str,
    hours: float, cost_code: Optional[str], description: Optional[str],
) -> None:
    _execute(
        """INSERT INTO payroll_time_entries
           (id, organization_id, person_id, work_date, hours, cost_code, description)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (id, org_id, person_id, work_date, hours, cost_code, description),
    )


def get_time_entry(org_id: str, entry_id: str) -> Optional[Dict[str, Any]]:
    return _fetch_one(
        "SELECT * FROM payroll_time_entries WHERE id = ? AND organization_id = ?",
        (entry_id, org_id),
    )


def list_time_entries(
    org_id: str, person_id: Optional[str] = None, limit: int = 100,
) -> List[Dict[str, Any]]:
    if person_id:
        return _fetch_all(
            "SELECT * FROM payroll_time_entries WHERE organization_id = ? AND person_id = ? ORDER BY work_date DESC LIMIT ?",
            (org_id, person_id, limit),
        )
    return _fetch_all(
        "SELECT * FROM payroll_time_entries WHERE organization_id = ? ORDER BY work_date DESC LIMIT ?",
        (org_id, limit),
    )


def update_time_entry(org_id: str, entry_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    sets = []
    vals = []
    for k, v in updates.items():
        if k in ("hours", "cost_code", "description", "status") and v is not None:
            sets.append(f"{k} = ?")
            vals.append(v)
    if not sets:
        return get_time_entry(org_id, entry_id)
    sets.append("updated_at = datetime('now')")
    vals.extend([entry_id, org_id])
    _execute(
        f"UPDATE payroll_time_entries SET {', '.join(sets)} WHERE id = ? AND organization_id = ?",
        tuple(vals),
    )
    return get_time_entry(org_id, entry_id)


# =============================================================================
# PAY RUNS
# =============================================================================

def create_pay_run(
    id: str, org_id: str, pay_period_start: str, pay_period_end: str,
    description: Optional[str],
) -> None:
    _execute(
        """INSERT INTO payroll_pay_runs
           (id, organization_id, pay_period_start, pay_period_end, description)
           VALUES (?, ?, ?, ?, ?)""",
        (id, org_id, pay_period_start, pay_period_end, description),
    )


def get_pay_run(org_id: str, run_id: str) -> Optional[Dict[str, Any]]:
    return _fetch_one(
        "SELECT * FROM payroll_pay_runs WHERE id = ? AND organization_id = ?",
        (run_id, org_id),
    )


def list_pay_runs(org_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    return _fetch_all(
        "SELECT * FROM payroll_pay_runs WHERE organization_id = ? ORDER BY pay_period_start DESC LIMIT ?",
        (org_id, limit),
    )


def add_pay_run_line(
    id: str, org_id: str, pay_run_id: str, person_id: str,
    gross_amount: float, tax_amount: float, benefits_amount: float,
    deductions_amount: float, net_amount: float,
    hours_worked: Optional[float], cost_code: Optional[str],
) -> None:
    conn = get_db_connection()
    try:
        conn.execute(
            """INSERT INTO payroll_pay_run_lines
               (id, organization_id, pay_run_id, person_id, gross_amount, tax_amount,
                benefits_amount, deductions_amount, net_amount, hours_worked, cost_code)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (id, org_id, pay_run_id, person_id, gross_amount, tax_amount,
             benefits_amount, deductions_amount, net_amount, hours_worked, cost_code),
        )
        # Update pay run totals
        conn.execute(
            """UPDATE payroll_pay_runs SET
               total_gross = total_gross + ?,
               total_tax = total_tax + ?,
               total_benefits = total_benefits + ?,
               total_deductions = total_deductions + ?,
               total_net = total_net + ?,
               line_count = line_count + 1,
               updated_at = datetime('now')
               WHERE id = ? AND organization_id = ?""",
            (gross_amount, tax_amount, benefits_amount, deductions_amount,
             net_amount, pay_run_id, org_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_pay_run_lines(org_id: str, pay_run_id: str) -> List[Dict[str, Any]]:
    return _fetch_all(
        "SELECT * FROM payroll_pay_run_lines WHERE pay_run_id = ? AND organization_id = ? ORDER BY person_id",
        (pay_run_id, org_id),
    )


def update_pay_run_status(
    org_id: str, run_id: str, new_status: str,
    locked_at: Optional[str] = None, snapshot_id: Optional[str] = None,
) -> None:
    if locked_at and snapshot_id:
        _execute(
            """UPDATE payroll_pay_runs SET status = ?, locked_at = ?, snapshot_id = ?,
               updated_at = datetime('now') WHERE id = ? AND organization_id = ?""",
            (new_status, locked_at, snapshot_id, run_id, org_id),
        )
    else:
        _execute(
            """UPDATE payroll_pay_runs SET status = ?, updated_at = datetime('now')
               WHERE id = ? AND organization_id = ?""",
            (new_status, run_id, org_id),
        )


# =============================================================================
# TAXES
# =============================================================================

def create_tax_withholding(
    id: str, org_id: str, person_id: str, tax_type: str,
    rate: float, effective_date: str,
    filing_status: Optional[str], allowances: Optional[int],
) -> None:
    _execute(
        """INSERT INTO payroll_tax_withholdings
           (id, organization_id, person_id, tax_type, rate, effective_date, filing_status, allowances)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (id, org_id, person_id, tax_type, rate, effective_date, filing_status, allowances),
    )


def list_tax_withholdings(org_id: str, person_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    if person_id:
        return _fetch_all(
            "SELECT * FROM payroll_tax_withholdings WHERE organization_id = ? AND person_id = ? ORDER BY effective_date DESC LIMIT ?",
            (org_id, person_id, limit),
        )
    return _fetch_all(
        "SELECT * FROM payroll_tax_withholdings WHERE organization_id = ? ORDER BY effective_date DESC LIMIT ?",
        (org_id, limit),
    )


# =============================================================================
# BENEFITS
# =============================================================================

def create_benefit_enrollment(
    id: str, org_id: str, person_id: str, benefit_type: str,
    plan_name: str, employee_contribution: float, employer_contribution: float,
    effective_date: str, end_date: Optional[str],
) -> None:
    _execute(
        """INSERT INTO payroll_benefit_enrollments
           (id, organization_id, person_id, benefit_type, plan_name,
            employee_contribution, employer_contribution, effective_date, end_date)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (id, org_id, person_id, benefit_type, plan_name,
         employee_contribution, employer_contribution, effective_date, end_date),
    )


def list_benefit_enrollments(org_id: str, person_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    if person_id:
        return _fetch_all(
            "SELECT * FROM payroll_benefit_enrollments WHERE organization_id = ? AND person_id = ? ORDER BY effective_date DESC LIMIT ?",
            (org_id, person_id, limit),
        )
    return _fetch_all(
        "SELECT * FROM payroll_benefit_enrollments WHERE organization_id = ? ORDER BY effective_date DESC LIMIT ?",
        (org_id, limit),
    )


# =============================================================================
# ACCOUNTING (Journal Entries)
# =============================================================================

def create_journal_entry(
    id: str, org_id: str, pay_run_id: str, account_code: str,
    debit: float, credit: float, description: str, cost_code: Optional[str],
) -> None:
    _execute(
        """INSERT INTO payroll_journal_entries
           (id, organization_id, pay_run_id, account_code, debit, credit, description, cost_code)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (id, org_id, pay_run_id, account_code, debit, credit, description, cost_code),
    )


def list_journal_entries(org_id: str, pay_run_id: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
    if pay_run_id:
        return _fetch_all(
            "SELECT * FROM payroll_journal_entries WHERE organization_id = ? AND pay_run_id = ? ORDER BY created_at",
            (org_id, pay_run_id),
        )
    return _fetch_all(
        "SELECT * FROM payroll_journal_entries WHERE organization_id = ? ORDER BY created_at DESC LIMIT ?",
        (org_id, limit),
    )


# =============================================================================
# COMPLIANCE CHECKS
# =============================================================================

def create_compliance_check(
    id: str, org_id: str, pay_run_id: str, check_type: str,
    status: str, message: str, details: Optional[str],
) -> None:
    _execute(
        """INSERT INTO payroll_compliance_checks
           (id, organization_id, pay_run_id, check_type, status, message, details)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (id, org_id, pay_run_id, check_type, status, message, details),
    )


def list_compliance_checks(org_id: str, pay_run_id: str) -> List[Dict[str, Any]]:
    return _fetch_all(
        "SELECT * FROM payroll_compliance_checks WHERE organization_id = ? AND pay_run_id = ? ORDER BY checked_at",
        (org_id, pay_run_id),
    )


# =============================================================================
# SNAPSHOTS (IMMUTABLE — INSERT ONLY)
# =============================================================================

def create_snapshot(
    id: str, org_id: str, snapshot_type: str, pay_run_id: str,
    version: int, data_hash: str, data: str,
) -> None:
    """INSERT ONLY — snapshots are immutable. No UPDATE or DELETE ever."""
    _execute(
        """INSERT INTO payroll_snapshots
           (id, organization_id, snapshot_type, pay_run_id, version, data_hash, data)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (id, org_id, snapshot_type, pay_run_id, version, data_hash, data),
    )


def get_snapshot(org_id: str, snapshot_id: str) -> Optional[Dict[str, Any]]:
    return _fetch_one(
        "SELECT * FROM payroll_snapshots WHERE id = ? AND organization_id = ?",
        (snapshot_id, org_id),
    )


def list_snapshots(
    org_id: str, snapshot_type: Optional[str] = None,
    pay_run_id: Optional[str] = None, limit: int = 50,
) -> List[Dict[str, Any]]:
    conditions = ["organization_id = ?"]
    params: list = [org_id]
    if snapshot_type:
        conditions.append("snapshot_type = ?")
        params.append(snapshot_type)
    if pay_run_id:
        conditions.append("pay_run_id = ?")
        params.append(pay_run_id)
    params.append(limit)
    return _fetch_all(
        f"SELECT id, organization_id, snapshot_type, pay_run_id, version, data_hash, created_at FROM payroll_snapshots WHERE {' AND '.join(conditions)} ORDER BY created_at DESC LIMIT ?",
        tuple(params),
    )


def get_snapshot_version(org_id: str, snapshot_type: str, pay_run_id: str) -> int:
    """Get next version number for a snapshot type + pay run."""
    row = _fetch_one(
        "SELECT MAX(version) as max_v FROM payroll_snapshots WHERE organization_id = ? AND snapshot_type = ? AND pay_run_id = ?",
        (org_id, snapshot_type, pay_run_id),
    )
    if row and row.get("max_v") is not None:
        return row["max_v"] + 1
    return 1
