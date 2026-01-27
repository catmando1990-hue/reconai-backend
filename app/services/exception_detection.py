# app/services/exception_detection.py
"""
Exception Detection Service - Deterministic Rule-Based Signal Generation

Phase 6.2 Implementation: Manual, deterministic exceptions engine that scans
existing data and APPENDS advisory signals into intelligence_signals.

CANONICAL LAWS:
- Deterministic rules only (no AI/ML, no heuristics)
- confidence = 1.0 (all detections are certain by definition)
- evidence_ref MUST include transaction_id(s) or query key
- Manual execution only (no auto-run, no background jobs, no triggers)
- APPEND-ONLY writes (no dedup, no mutation of source tables)
- Audit logging REQUIRED after each run

APPROVED TAXONOMY (E1-E6) — LOCKED:
- E1: Uncategorized Transaction
- E2: Duplicate Transaction
- E3: Amount Threshold Breach
- E4: Out-of-Period Posting
- E5: Missing Counterparty
- E6: Negative Balance Event

PROHIBITIONS (HARD STOP):
- No automatic execution
- No triggers, cron, or polling
- No updates/deletes to source data
- No confidence < 1.0
- No schema changes
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, asdict
from datetime import date, datetime
from typing import List, Optional, Dict, Any, Tuple

from app.db import get_db_connection


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class DetectedSignal:
    """A signal detected by a rule."""
    rule_id: str
    title: str
    description: str
    evidence_ref: str  # JSON-encoded reference to source data


@dataclass
class DetectionResult:
    """Result of running exception detection."""
    organization_id: str
    request_id: str
    signals_detected: int
    signals_inserted: int
    signals_by_rule: Dict[str, int]
    threshold_used: float
    period_start: Optional[str]
    period_end: Optional[str]
    errors: List[str]
    executed_at: str


# =============================================================================
# APPROVED TAXONOMY (E1-E6) — LOCKED
# =============================================================================

RULE_TITLES = {
    "E1": "Uncategorized Transaction",
    "E2": "Duplicate Transaction",
    "E3": "Amount Threshold Breach",
    "E4": "Out-of-Period Posting",
    "E5": "Missing Counterparty",
    "E6": "Negative Balance Event",
}

RULESET_VERSION = "E1-E6 v1"


# =============================================================================
# E1 — Uncategorized Transaction
# =============================================================================
# Condition: category IS NULL OR TRIM(category) = ''

def _detect_e1_uncategorized(conn, organization_id: str) -> List[DetectedSignal]:
    """E1: Uncategorized Transaction"""
    sql = """
        SELECT id, name, date, amount
        FROM core_transactions
        WHERE organization_id = ?
          AND (category IS NULL OR TRIM(category) = '')
        ORDER BY date DESC
    """
    cursor = conn.cursor()
    cursor.execute(sql, (organization_id,))
    rows = cursor.fetchall()

    signals = []
    for row in rows:
        tx_id, name, tx_date, amount = row
        signals.append(DetectedSignal(
            rule_id="E1",
            title=RULE_TITLES["E1"],
            description=f"Transaction '{name or 'Unknown'}' on {tx_date} for ${abs(amount):.2f} has no category assigned.",
            evidence_ref=json.dumps({"transaction_id": tx_id, "rule": "E1"})
        ))

    return signals


# =============================================================================
# E2 — Duplicate Transaction (Exact Match)
# =============================================================================
# Condition: GROUP BY amount, date, account_id, name HAVING COUNT(*) > 1

def _detect_e2_duplicates(conn, organization_id: str) -> List[DetectedSignal]:
    """E2: Duplicate Transaction (exact match on amount, date, account_id, name)"""
    sql = """
        SELECT amount, date, account_id, name, COUNT(*) as cnt, GROUP_CONCAT(id) as ids
        FROM core_transactions
        WHERE organization_id = ?
        GROUP BY amount, date, account_id, name
        HAVING COUNT(*) > 1
        ORDER BY date DESC
    """
    cursor = conn.cursor()
    cursor.execute(sql, (organization_id,))
    rows = cursor.fetchall()

    signals = []
    for row in rows:
        amount, tx_date, account_id, name, count, ids = row
        signals.append(DetectedSignal(
            rule_id="E2",
            title=RULE_TITLES["E2"],
            description=f"Duplicate detected: '{name or 'Unknown'}' on {tx_date} for ${abs(amount):.2f} (account: {account_id or 'N/A'}). {count} occurrences.",
            evidence_ref=json.dumps({
                "transaction_ids": ids.split(",") if ids else [],
                "rule": "E2",
                "count": count
            })
        ))

    return signals


# =============================================================================
# E3 — Amount Threshold Breach
# =============================================================================
# Condition: ABS(amount) >= threshold (default: 10000)

def _detect_e3_amount_threshold(conn, organization_id: str, threshold: float) -> List[DetectedSignal]:
    """E3: Amount Threshold Breach"""
    sql = """
        SELECT id, name, date, amount
        FROM core_transactions
        WHERE organization_id = ?
          AND ABS(amount) >= ?
        ORDER BY ABS(amount) DESC, date DESC
    """
    cursor = conn.cursor()
    cursor.execute(sql, (organization_id, threshold))
    rows = cursor.fetchall()

    signals = []
    for row in rows:
        tx_id, name, tx_date, amount = row
        signals.append(DetectedSignal(
            rule_id="E3",
            title=RULE_TITLES["E3"],
            description=f"Transaction '{name or 'Unknown'}' on {tx_date} exceeds threshold: ${abs(amount):.2f} (threshold: ${threshold:.2f}).",
            evidence_ref=json.dumps({
                "transaction_id": tx_id,
                "rule": "E3",
                "threshold": threshold,
                "amount": float(amount)
            })
        ))

    return signals


# =============================================================================
# E4 — Out-of-Period Posting
# =============================================================================
# Condition: date NOT BETWEEN period_start AND period_end
# HARD STOP: If period_start/period_end not provided, skip and report error

def _detect_e4_out_of_period(
    conn,
    organization_id: str,
    period_start: Optional[str],
    period_end: Optional[str]
) -> Tuple[List[DetectedSignal], Optional[str]]:
    """
    E4: Out-of-Period Posting

    Returns: (signals, error_message)
    If period not provided, returns empty list and error message (HARD STOP)
    """
    if not period_start or not period_end:
        return [], "E4 SKIPPED: period_start and period_end are REQUIRED for Out-of-Period detection"

    sql = """
        SELECT id, name, date, amount
        FROM core_transactions
        WHERE organization_id = ?
          AND date NOT BETWEEN ? AND ?
        ORDER BY date DESC
    """
    cursor = conn.cursor()
    cursor.execute(sql, (organization_id, period_start, period_end))
    rows = cursor.fetchall()

    signals = []
    for row in rows:
        tx_id, name, tx_date, amount = row
        signals.append(DetectedSignal(
            rule_id="E4",
            title=RULE_TITLES["E4"],
            description=f"Transaction '{name or 'Unknown'}' dated {tx_date} is outside period ({period_start} to {period_end}).",
            evidence_ref=json.dumps({
                "transaction_id": tx_id,
                "rule": "E4",
                "period_start": period_start,
                "period_end": period_end
            })
        ))

    return signals, None


# =============================================================================
# E5 — Missing Counterparty
# =============================================================================
# Condition: No linked vendor or customer
# Note: Schema uses linked_vendor_id/linked_customer_id (adapting from spec's "counterparty")

def _detect_e5_missing_counterparty(conn, organization_id: str) -> List[DetectedSignal]:
    """E5: Missing Counterparty (no linked vendor or customer)"""
    sql = """
        SELECT id, name, date, amount
        FROM core_transactions
        WHERE organization_id = ?
          AND (linked_vendor_id IS NULL OR TRIM(linked_vendor_id) = '')
          AND (linked_customer_id IS NULL OR TRIM(linked_customer_id) = '')
        ORDER BY date DESC
    """
    cursor = conn.cursor()
    cursor.execute(sql, (organization_id,))
    rows = cursor.fetchall()

    signals = []
    for row in rows:
        tx_id, name, tx_date, amount = row
        signals.append(DetectedSignal(
            rule_id="E5",
            title=RULE_TITLES["E5"],
            description=f"Transaction '{name or 'Unknown'}' on {tx_date} for ${abs(amount):.2f} has no linked vendor or customer.",
            evidence_ref=json.dumps({"transaction_id": tx_id, "rule": "E5"})
        ))

    return signals


# =============================================================================
# E6 — Negative Balance Event
# =============================================================================
# Condition: running_balance < 0 (calculated via window function)

def _detect_e6_negative_balance(conn, organization_id: str) -> List[DetectedSignal]:
    """E6: Negative Balance Event (running balance < 0)"""
    sql = """
        WITH running_balances AS (
            SELECT
                id,
                account_id,
                date,
                amount,
                SUM(amount) OVER (
                    PARTITION BY account_id
                    ORDER BY date, id
                    ROWS UNBOUNDED PRECEDING
                ) as running_balance
            FROM core_transactions
            WHERE organization_id = ?
              AND account_id IS NOT NULL
        )
        SELECT id, account_id, date, running_balance
        FROM running_balances
        WHERE running_balance < 0
        ORDER BY date DESC
    """
    cursor = conn.cursor()
    cursor.execute(sql, (organization_id,))
    rows = cursor.fetchall()

    signals = []
    for row in rows:
        tx_id, account_id, tx_date, balance = row
        signals.append(DetectedSignal(
            rule_id="E6",
            title=RULE_TITLES["E6"],
            description=f"Account {account_id} reached negative balance of ${abs(balance):.2f} after transaction on {tx_date}.",
            evidence_ref=json.dumps({
                "transaction_id": tx_id,
                "account_id": account_id,
                "rule": "E6",
                "running_balance": float(balance)
            })
        ))

    return signals


# =============================================================================
# SIGNAL INSERTION (APPEND-ONLY)
# =============================================================================

def _insert_signals(conn, organization_id: str, signals: List[DetectedSignal]) -> int:
    """
    APPEND signals into intelligence_signals table.

    MANDATORY SHAPE per spec:
    - confidence MUST be 1.0
    - created_at via datetime('now')
    - NO dedup unless explicitly instructed
    """
    if not signals:
        return 0

    sql = """
        INSERT INTO intelligence_signals (
            organization_id,
            title,
            description,
            confidence,
            evidence_ref,
            created_at
        )
        VALUES (?, ?, ?, 1.0, ?, datetime('now'))
    """

    cursor = conn.cursor()
    inserted = 0

    for signal in signals:
        cursor.execute(sql, (
            organization_id,
            signal.title,
            signal.description,
            signal.evidence_ref
        ))
        inserted += 1

    conn.commit()
    return inserted


# =============================================================================
# AUDIT LOGGING (REQUIRED)
# =============================================================================

def _write_audit_event(
    conn,
    organization_id: str,
    threshold_used: float,
    signals_created_count: int,
    period_start: Optional[str],
    period_end: Optional[str],
    request_id: str
) -> None:
    """
    Append ONE audit event after each detection run.

    event_type: "exception_detection_run"
    metadata includes: ruleset, threshold_used, signals_created_count
    """
    from app.services.audit_store import AuditEventInput, insert_audit_event

    metadata = {
        "ruleset": RULESET_VERSION,
        "threshold_used": threshold_used,
        "signals_created_count": signals_created_count,
        "period_start": period_start,
        "period_end": period_end,
        "request_id": request_id
    }

    audit_input = AuditEventInput(
        actor_id="system",
        event_type="exception_detection_run",
        entity_type="intelligence_signals",
        entity_id=organization_id,
        payload=metadata
    )

    insert_audit_event(audit_input)


# =============================================================================
# MAIN EXECUTION FUNCTION (MANUAL ONLY)
# =============================================================================

def run_exception_detection(
    organization_id: str,
    threshold: float = 10000.0,
    period_start: Optional[str] = None,
    period_end: Optional[str] = None,
    request_id: Optional[str] = None,
    rules: Optional[List[str]] = None
) -> DetectionResult:
    """
    Run deterministic exception detection for an organization.

    MANUAL EXECUTION ONLY — invoked explicitly (admin/tooling), NOT on request paths.
    One invocation = one scan + one batch insert.

    Args:
        organization_id: Organization to scan
        threshold: Amount threshold for E3 (default: 10000)
        period_start: Period start date for E4 (YYYY-MM-DD). Required for E4.
        period_end: Period end date for E4 (YYYY-MM-DD). Required for E4.
        request_id: Request ID for audit tracing (auto-generated if not provided)
        rules: List of rule IDs to run (None = all rules E1-E6)

    Returns:
        DetectionResult with counts and execution details

    APPEND-ONLY: Does NOT dedupe. Does NOT clear existing signals.
    """
    if not request_id:
        request_id = str(uuid.uuid4())

    conn = get_db_connection()
    errors: List[str] = []
    all_signals: List[DetectedSignal] = []
    signals_by_rule: Dict[str, int] = {
        "E1": 0, "E2": 0, "E3": 0, "E4": 0, "E5": 0, "E6": 0
    }

    # Determine which rules to run
    rules_to_run = rules if rules else ["E1", "E2", "E3", "E4", "E5", "E6"]

    # Run E1 — Uncategorized Transaction
    if "E1" in rules_to_run:
        try:
            detected = _detect_e1_uncategorized(conn, organization_id)
            signals_by_rule["E1"] = len(detected)
            all_signals.extend(detected)
        except Exception as e:
            errors.append(f"E1 failed: {str(e)}")

    # Run E2 — Duplicate Transaction
    if "E2" in rules_to_run:
        try:
            detected = _detect_e2_duplicates(conn, organization_id)
            signals_by_rule["E2"] = len(detected)
            all_signals.extend(detected)
        except Exception as e:
            errors.append(f"E2 failed: {str(e)}")

    # Run E3 — Amount Threshold Breach
    if "E3" in rules_to_run:
        try:
            detected = _detect_e3_amount_threshold(conn, organization_id, threshold)
            signals_by_rule["E3"] = len(detected)
            all_signals.extend(detected)
        except Exception as e:
            errors.append(f"E3 failed: {str(e)}")

    # Run E4 — Out-of-Period Posting (requires period params)
    if "E4" in rules_to_run:
        try:
            detected, e4_error = _detect_e4_out_of_period(conn, organization_id, period_start, period_end)
            if e4_error:
                errors.append(e4_error)
            signals_by_rule["E4"] = len(detected)
            all_signals.extend(detected)
        except Exception as e:
            errors.append(f"E4 failed: {str(e)}")

    # Run E5 — Missing Counterparty
    if "E5" in rules_to_run:
        try:
            detected = _detect_e5_missing_counterparty(conn, organization_id)
            signals_by_rule["E5"] = len(detected)
            all_signals.extend(detected)
        except Exception as e:
            errors.append(f"E5 failed: {str(e)}")

    # Run E6 — Negative Balance Event
    if "E6" in rules_to_run:
        try:
            detected = _detect_e6_negative_balance(conn, organization_id)
            signals_by_rule["E6"] = len(detected)
            all_signals.extend(detected)
        except Exception as e:
            errors.append(f"E6 failed: {str(e)}")

    # Insert signals (APPEND-ONLY, no dedup)
    inserted = 0
    try:
        inserted = _insert_signals(conn, organization_id, all_signals)
    except Exception as e:
        errors.append(f"Signal insertion failed: {str(e)}")

    conn.close()

    # Audit logging (REQUIRED — exactly once per run)
    try:
        audit_conn = get_db_connection()
        _write_audit_event(
            audit_conn,
            organization_id,
            threshold,
            inserted,
            period_start,
            period_end,
            request_id
        )
        audit_conn.close()
    except Exception as e:
        errors.append(f"Audit logging failed: {str(e)}")

    executed_at = datetime.utcnow().isoformat() + "Z"

    return DetectionResult(
        organization_id=organization_id,
        request_id=request_id,
        signals_detected=len(all_signals),
        signals_inserted=inserted,
        signals_by_rule=signals_by_rule,
        threshold_used=threshold,
        period_start=period_start,
        period_end=period_end,
        errors=errors,
        executed_at=executed_at
    )


def get_detection_rules() -> Dict[str, str]:
    """
    Get list of available detection rules.

    Returns:
        Dict mapping rule_id (E1-E6) to title
    """
    return RULE_TITLES.copy()
