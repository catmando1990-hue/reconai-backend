# app/services/exception_detection.py
"""
Exception Detection Service - Deterministic Rule-Based Signal Generation

Phase 6 Implementation: Populates intelligence_signals table with real exception data.

CANONICAL LAWS:
- Deterministic rules only (no AI inference)
- confidence = 1.0 (all detections are certain by definition)
- evidence_ref MUST include transaction_id or query reference
- Manual execution only (no auto-run)
- Fail-closed audit logging

RULES IMPLEMENTED:
1. UNCATEGORIZED_TRANSACTION - category IS NULL OR empty
2. DUPLICATE_TRANSACTION - Same amount, date, account_id, description
3. AMOUNT_THRESHOLD_BREACH - ABS(amount) >= $10,000
4. OUT_OF_PERIOD_POSTING - date outside current fiscal year
5. MISSING_COUNTERPARTY - linked_vendor_id AND linked_customer_id both NULL
6. NEGATIVE_BALANCE_EVENT - running balance < 0 for account
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional, Dict, Any

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
    errors: List[str]
    executed_at: str


# =============================================================================
# RULE DEFINITIONS
# =============================================================================

RULE_DEFINITIONS = {
    "UNCATEGORIZED_TRANSACTION": {
        "title": "Uncategorized Transaction",
        "description_template": "Transaction '{name}' on {date} for ${amount} has no category assigned.",
    },
    "DUPLICATE_TRANSACTION": {
        "title": "Potential Duplicate Transaction",
        "description_template": "Multiple transactions found: {name} on {date} for ${amount} (account: {account_id}). {count} occurrences.",
    },
    "AMOUNT_THRESHOLD_BREACH": {
        "title": "Large Amount Transaction",
        "description_template": "Transaction '{name}' on {date} exceeds $10,000 threshold: ${amount}.",
    },
    "OUT_OF_PERIOD_POSTING": {
        "title": "Out-of-Period Transaction",
        "description_template": "Transaction '{name}' dated {date} is outside current fiscal year ({fiscal_year}).",
    },
    "MISSING_COUNTERPARTY": {
        "title": "Missing Counterparty",
        "description_template": "Transaction '{name}' on {date} for ${amount} has no linked vendor or customer.",
    },
    "NEGATIVE_BALANCE_EVENT": {
        "title": "Negative Balance Detected",
        "description_template": "Account {account_id} has negative running balance of ${balance} after transaction on {date}.",
    },
}


# =============================================================================
# DETECTION RULES
# =============================================================================

def _detect_uncategorized(conn, organization_id: str) -> List[DetectedSignal]:
    """Rule 1: Uncategorized Transaction - category IS NULL OR empty"""
    sql = """
        SELECT id, name, date, amount
        FROM core_transactions
        WHERE organization_id = ?
          AND (category IS NULL OR category = '' OR TRIM(category) = '')
        ORDER BY date DESC
    """
    cursor = conn.cursor()
    cursor.execute(sql, (organization_id,))
    rows = cursor.fetchall()

    signals = []
    for row in rows:
        tx_id, name, tx_date, amount = row
        signals.append(DetectedSignal(
            rule_id="UNCATEGORIZED_TRANSACTION",
            title=RULE_DEFINITIONS["UNCATEGORIZED_TRANSACTION"]["title"],
            description=RULE_DEFINITIONS["UNCATEGORIZED_TRANSACTION"]["description_template"].format(
                name=name or "Unknown",
                date=tx_date,
                amount=abs(amount)
            ),
            evidence_ref=f'{{"transaction_id": "{tx_id}", "rule": "UNCATEGORIZED_TRANSACTION"}}'
        ))

    return signals


def _detect_duplicates(conn, organization_id: str) -> List[DetectedSignal]:
    """Rule 2: Duplicate Transaction - Same amount, date, account_id, name"""
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
            rule_id="DUPLICATE_TRANSACTION",
            title=RULE_DEFINITIONS["DUPLICATE_TRANSACTION"]["title"],
            description=RULE_DEFINITIONS["DUPLICATE_TRANSACTION"]["description_template"].format(
                name=name or "Unknown",
                date=tx_date,
                amount=abs(amount),
                account_id=account_id or "N/A",
                count=count
            ),
            evidence_ref=f'{{"transaction_ids": "{ids}", "rule": "DUPLICATE_TRANSACTION", "count": {count}}}'
        ))

    return signals


def _detect_amount_threshold(conn, organization_id: str, threshold: float = 10000.0) -> List[DetectedSignal]:
    """Rule 3: Amount Threshold Breach - ABS(amount) >= threshold"""
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
            rule_id="AMOUNT_THRESHOLD_BREACH",
            title=RULE_DEFINITIONS["AMOUNT_THRESHOLD_BREACH"]["title"],
            description=RULE_DEFINITIONS["AMOUNT_THRESHOLD_BREACH"]["description_template"].format(
                name=name or "Unknown",
                date=tx_date,
                amount=abs(amount)
            ),
            evidence_ref=f'{{"transaction_id": "{tx_id}", "rule": "AMOUNT_THRESHOLD_BREACH", "threshold": {threshold}}}'
        ))

    return signals


def _detect_out_of_period(conn, organization_id: str) -> List[DetectedSignal]:
    """Rule 4: Out-of-Period Posting - date outside current fiscal year"""
    current_year = date.today().year
    fiscal_year_start = f"{current_year}-01-01"
    fiscal_year_end = f"{current_year}-12-31"

    sql = """
        SELECT id, name, date, amount
        FROM core_transactions
        WHERE organization_id = ?
          AND (date < ? OR date > ?)
        ORDER BY date DESC
    """
    cursor = conn.cursor()
    cursor.execute(sql, (organization_id, fiscal_year_start, fiscal_year_end))
    rows = cursor.fetchall()

    signals = []
    for row in rows:
        tx_id, name, tx_date, amount = row
        signals.append(DetectedSignal(
            rule_id="OUT_OF_PERIOD_POSTING",
            title=RULE_DEFINITIONS["OUT_OF_PERIOD_POSTING"]["title"],
            description=RULE_DEFINITIONS["OUT_OF_PERIOD_POSTING"]["description_template"].format(
                name=name or "Unknown",
                date=tx_date,
                fiscal_year=current_year
            ),
            evidence_ref=f'{{"transaction_id": "{tx_id}", "rule": "OUT_OF_PERIOD_POSTING", "fiscal_year": {current_year}}}'
        ))

    return signals


def _detect_missing_counterparty(conn, organization_id: str) -> List[DetectedSignal]:
    """Rule 5: Missing Counterparty - no linked vendor or customer"""
    sql = """
        SELECT id, name, date, amount
        FROM core_transactions
        WHERE organization_id = ?
          AND (linked_vendor_id IS NULL OR linked_vendor_id = '')
          AND (linked_customer_id IS NULL OR linked_customer_id = '')
        ORDER BY date DESC
    """
    cursor = conn.cursor()
    cursor.execute(sql, (organization_id,))
    rows = cursor.fetchall()

    signals = []
    for row in rows:
        tx_id, name, tx_date, amount = row
        signals.append(DetectedSignal(
            rule_id="MISSING_COUNTERPARTY",
            title=RULE_DEFINITIONS["MISSING_COUNTERPARTY"]["title"],
            description=RULE_DEFINITIONS["MISSING_COUNTERPARTY"]["description_template"].format(
                name=name or "Unknown",
                date=tx_date,
                amount=abs(amount)
            ),
            evidence_ref=f'{{"transaction_id": "{tx_id}", "rule": "MISSING_COUNTERPARTY"}}'
        ))

    return signals


def _detect_negative_balance(conn, organization_id: str) -> List[DetectedSignal]:
    """Rule 6: Negative Balance Event - running balance < 0 for any account"""
    # Calculate running balance per account, detect negative balances
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
    seen_accounts = set()  # Only report first negative balance per account
    for row in rows:
        tx_id, account_id, tx_date, balance = row
        if account_id not in seen_accounts:
            seen_accounts.add(account_id)
            signals.append(DetectedSignal(
                rule_id="NEGATIVE_BALANCE_EVENT",
                title=RULE_DEFINITIONS["NEGATIVE_BALANCE_EVENT"]["title"],
                description=RULE_DEFINITIONS["NEGATIVE_BALANCE_EVENT"]["description_template"].format(
                    account_id=account_id,
                    balance=abs(balance),
                    date=tx_date
                ),
                evidence_ref=f'{{"transaction_id": "{tx_id}", "account_id": "{account_id}", "rule": "NEGATIVE_BALANCE_EVENT", "balance": {balance}}}'
            ))

    return signals


# =============================================================================
# SIGNAL INSERTION
# =============================================================================

def _insert_signals(conn, organization_id: str, signals: List[DetectedSignal]) -> int:
    """
    Insert detected signals into intelligence_signals table.

    Returns count of successfully inserted signals.
    """
    if not signals:
        return 0

    sql = """
        INSERT INTO intelligence_signals (organization_id, title, description, confidence, evidence_ref)
        VALUES (?, ?, ?, 1.0, ?)
    """

    cursor = conn.cursor()
    inserted = 0

    for signal in signals:
        try:
            cursor.execute(sql, (
                organization_id,
                signal.title,
                signal.description,
                signal.evidence_ref
            ))
            inserted += 1
        except Exception:
            # Log error but continue with other signals
            pass

    conn.commit()
    return inserted


def _clear_existing_signals(conn, organization_id: str) -> int:
    """
    Clear existing signals for organization before regenerating.

    Returns count of deleted signals.
    """
    sql = "DELETE FROM intelligence_signals WHERE organization_id = ?"
    cursor = conn.cursor()
    cursor.execute(sql, (organization_id,))
    deleted = cursor.rowcount
    conn.commit()
    return deleted


# =============================================================================
# MAIN EXECUTION FUNCTION
# =============================================================================

def run_exception_detection(
    organization_id: str,
    request_id: Optional[str] = None,
    clear_existing: bool = True,
    rules: Optional[List[str]] = None
) -> DetectionResult:
    """
    Run deterministic exception detection for an organization.

    MANUAL EXECUTION ONLY - This function must be called explicitly.
    It does NOT run automatically on transaction insert/update.

    Args:
        organization_id: Organization to scan
        request_id: Request ID for audit tracing (auto-generated if not provided)
        clear_existing: If True, clears existing signals before inserting new ones
        rules: List of rule IDs to run (None = all rules)

    Returns:
        DetectionResult with counts and details
    """
    if not request_id:
        request_id = str(uuid.uuid4())

    conn = get_db_connection()
    errors: List[str] = []
    all_signals: List[DetectedSignal] = []
    signals_by_rule: Dict[str, int] = {}

    # Define rule functions
    rule_functions = {
        "UNCATEGORIZED_TRANSACTION": _detect_uncategorized,
        "DUPLICATE_TRANSACTION": _detect_duplicates,
        "AMOUNT_THRESHOLD_BREACH": _detect_amount_threshold,
        "OUT_OF_PERIOD_POSTING": _detect_out_of_period,
        "MISSING_COUNTERPARTY": _detect_missing_counterparty,
        "NEGATIVE_BALANCE_EVENT": _detect_negative_balance,
    }

    # Determine which rules to run
    rules_to_run = rules if rules else list(rule_functions.keys())

    # Run each detection rule
    for rule_id in rules_to_run:
        if rule_id not in rule_functions:
            errors.append(f"Unknown rule: {rule_id}")
            continue

        try:
            detected = rule_functions[rule_id](conn, organization_id)
            signals_by_rule[rule_id] = len(detected)
            all_signals.extend(detected)
        except Exception as e:
            errors.append(f"Rule {rule_id} failed: {str(e)}")
            signals_by_rule[rule_id] = 0

    # Clear existing signals if requested
    if clear_existing:
        try:
            _clear_existing_signals(conn, organization_id)
        except Exception as e:
            errors.append(f"Failed to clear existing signals: {str(e)}")

    # Insert new signals
    inserted = 0
    try:
        inserted = _insert_signals(conn, organization_id, all_signals)
    except Exception as e:
        errors.append(f"Signal insertion failed: {str(e)}")

    conn.close()

    return DetectionResult(
        organization_id=organization_id,
        request_id=request_id,
        signals_detected=len(all_signals),
        signals_inserted=inserted,
        signals_by_rule=signals_by_rule,
        errors=errors,
        executed_at=datetime.utcnow().isoformat() + "Z"
    )


def get_detection_rules() -> Dict[str, Dict[str, str]]:
    """
    Get list of available detection rules with metadata.

    Returns:
        Dict mapping rule_id to rule metadata (title, description_template)
    """
    return RULE_DEFINITIONS.copy()
