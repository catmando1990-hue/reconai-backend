# app/payroll/snapshots.py
"""
Payroll Snapshot Service — Immutable, Hash-Sealed

Generates three snapshot types when pay runs are LOCKED:
  1. PAYROLL — Full pay run + line items
  2. LABOR_DISTRIBUTION — Time entries grouped by cost code
  3. TAX_LIABILITY — Tax withholdings for all employees in the run

CANONICAL LAWS:
- Snapshots are INSERT-ONLY (no UPDATE, no DELETE)
- Every snapshot is SHA-256 hash-sealed
- Versioned per (org, type, pay_run_id)
- Generated ONLY on pay run lock (irreversible)
- Payroll NEVER calls DCAA or CFO directly
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Dict, List

from app.payroll import db as payroll_db


def _new_id() -> str:
    return str(uuid.uuid4())


def _hash_data(data: Dict[str, Any]) -> str:
    """Deterministic SHA-256 hash of snapshot data."""
    canonical = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def generate_payroll_snapshot(
    org_id: str,
    pay_run_id: str,
    pay_run: Dict[str, Any],
    line_items: List[Dict[str, Any]],
) -> str:
    """
    Generate an immutable payroll snapshot.

    Returns the snapshot ID.
    """
    version = payroll_db.get_snapshot_version(org_id, "payroll", pay_run_id)
    snapshot_id = _new_id()

    data = {
        "snapshot_type": "payroll",
        "pay_run": pay_run,
        "line_items": line_items,
        "line_count": len(line_items),
        "total_gross": pay_run.get("total_gross", 0),
        "total_net": pay_run.get("total_net", 0),
    }
    data_hash = _hash_data(data)

    payroll_db.create_snapshot(
        id=snapshot_id,
        org_id=org_id,
        snapshot_type="payroll",
        pay_run_id=pay_run_id,
        version=version,
        data_hash=data_hash,
        data=json.dumps(data, sort_keys=True, default=str),
    )
    return snapshot_id


def generate_labor_distribution_snapshot(
    org_id: str,
    pay_run_id: str,
    pay_run: Dict[str, Any],
    line_items: List[Dict[str, Any]],
) -> str:
    """
    Generate a labor distribution snapshot grouped by cost code.

    Returns the snapshot ID.
    """
    version = payroll_db.get_snapshot_version(org_id, "labor_distribution", pay_run_id)
    snapshot_id = _new_id()

    # Group line items by cost_code
    by_cost_code: Dict[str, List[Dict[str, Any]]] = {}
    for item in line_items:
        code = item.get("cost_code") or "unassigned"
        by_cost_code.setdefault(code, []).append(item)

    distribution = []
    for code, items in sorted(by_cost_code.items()):
        distribution.append({
            "cost_code": code,
            "line_count": len(items),
            "total_gross": sum(i.get("gross_amount", 0) for i in items),
            "total_hours": sum(i.get("hours_worked", 0) or 0 for i in items),
            "person_ids": [i.get("person_id") for i in items],
        })

    data = {
        "snapshot_type": "labor_distribution",
        "pay_period_start": pay_run.get("pay_period_start"),
        "pay_period_end": pay_run.get("pay_period_end"),
        "distribution": distribution,
    }
    data_hash = _hash_data(data)

    payroll_db.create_snapshot(
        id=snapshot_id,
        org_id=org_id,
        snapshot_type="labor_distribution",
        pay_run_id=pay_run_id,
        version=version,
        data_hash=data_hash,
        data=json.dumps(data, sort_keys=True, default=str),
    )
    return snapshot_id


def generate_tax_liability_snapshot(
    org_id: str,
    pay_run_id: str,
    pay_run: Dict[str, Any],
    line_items: List[Dict[str, Any]],
) -> str:
    """
    Generate a tax liability snapshot for all employees in the run.

    Returns the snapshot ID.
    """
    version = payroll_db.get_snapshot_version(org_id, "tax_liability", pay_run_id)
    snapshot_id = _new_id()

    # Collect person IDs from line items
    person_ids = list({item.get("person_id") for item in line_items if item.get("person_id")})

    # Gather tax withholdings for each person
    tax_records = []
    for pid in sorted(person_ids):
        withholdings = payroll_db.list_tax_withholdings(org_id, person_id=pid)
        for w in withholdings:
            tax_records.append({
                "person_id": pid,
                "tax_type": w.get("tax_type"),
                "rate": w.get("rate"),
                "effective_date": w.get("effective_date"),
                "filing_status": w.get("filing_status"),
            })

    total_tax = sum(i.get("tax_amount", 0) for i in line_items)

    data = {
        "snapshot_type": "tax_liability",
        "pay_period_start": pay_run.get("pay_period_start"),
        "pay_period_end": pay_run.get("pay_period_end"),
        "total_tax": total_tax,
        "tax_records": tax_records,
        "employee_count": len(person_ids),
    }
    data_hash = _hash_data(data)

    payroll_db.create_snapshot(
        id=snapshot_id,
        org_id=org_id,
        snapshot_type="tax_liability",
        pay_run_id=pay_run_id,
        version=version,
        data_hash=data_hash,
        data=json.dumps(data, sort_keys=True, default=str),
    )
    return snapshot_id


def generate_all_snapshots(
    org_id: str,
    pay_run_id: str,
    pay_run: Dict[str, Any],
    line_items: List[Dict[str, Any]],
) -> Dict[str, str]:
    """
    Generate all three snapshot types for a locked pay run.

    Returns dict mapping snapshot_type -> snapshot_id.
    """
    return {
        "payroll": generate_payroll_snapshot(org_id, pay_run_id, pay_run, line_items),
        "labor_distribution": generate_labor_distribution_snapshot(org_id, pay_run_id, pay_run, line_items),
        "tax_liability": generate_tax_liability_snapshot(org_id, pay_run_id, pay_run, line_items),
    }
