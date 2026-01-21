# app/intelligence/duplicates.py
"""
Duplicate Transaction Detection (Non-Destructive)

Detects potential duplicate transactions using hash/date/amount matching.
NEVER deletes or modifies transactions - advisory only.

CANONICAL LAWS:
- Read-only: detection only, no mutations
- Deterministic: same input produces same output
- Evidence-based: every duplicate group has traceable signals
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from uuid import uuid4

from app.intelligence.models import (
    DuplicateGroup,
    EvidenceItem,
)


@dataclass
class TransactionData:
    """Minimal transaction data for duplicate detection."""

    transaction_id: str
    tx_date: Optional[str]
    amount: float
    description: str
    merchant: Optional[str]


def _compute_identity_hash(tx: TransactionData) -> str:
    """
    Compute deterministic identity hash for a transaction.

    Hash is based on: merchant (normalized) + amount + date
    """
    merchant_norm = (tx.merchant or "").lower().strip()
    date_norm = (tx.tx_date or "")[:10]  # YYYY-MM-DD only
    amount_norm = f"{abs(tx.amount):.2f}"

    identity_string = f"{merchant_norm}|{amount_norm}|{date_norm}"
    return hashlib.sha256(identity_string.encode()).hexdigest()[:16]


def _parse_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parse date string to datetime."""
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00").split("T")[0])
    except (ValueError, AttributeError):
        return None


def _dates_within_window(
    date1: Optional[str], date2: Optional[str], window_hours: int = 72
) -> bool:
    """Check if two dates are within the specified window."""
    d1 = _parse_date(date1)
    d2 = _parse_date(date2)
    if d1 is None or d2 is None:
        return False
    delta = abs((d1 - d2).total_seconds())
    return delta <= (window_hours * 3600)


def _amounts_match(amount1: float, amount2: float, tolerance: float = 0.01) -> bool:
    """Check if amounts match within tolerance."""
    return abs(amount1 - amount2) <= tolerance


def _merchants_match(merchant1: Optional[str], merchant2: Optional[str]) -> bool:
    """Check if merchants match (case-insensitive, normalized)."""
    if not merchant1 or not merchant2:
        return False
    m1 = merchant1.lower().strip()
    m2 = merchant2.lower().strip()
    return m1 == m2


def detect_duplicates(
    transactions: List[TransactionData],
    time_window_hours: int = 72,
    amount_tolerance: float = 0.01,
) -> List[DuplicateGroup]:
    """
    Detect potential duplicate transactions.

    Detection criteria (all must match for high confidence):
    1. Same merchant (normalized)
    2. Same amount (within tolerance)
    3. Within time window

    Returns:
        List of DuplicateGroup objects for review
    """
    if len(transactions) < 2:
        return []

    # Group by identity hash for initial clustering
    hash_groups: Dict[str, List[TransactionData]] = defaultdict(list)
    for tx in transactions:
        identity_hash = _compute_identity_hash(tx)
        hash_groups[identity_hash].append(tx)

    # Filter to groups with 2+ transactions (potential duplicates)
    duplicate_groups: List[DuplicateGroup] = []

    for identity_hash, group_txs in hash_groups.items():
        if len(group_txs) < 2:
            continue

        # Calculate confidence based on matching signals
        evidence: List[EvidenceItem] = []
        confidence = 0.5  # Base confidence for hash match

        # Check all pairs in group
        first_tx = group_txs[0]
        all_merchants_match = True
        all_amounts_match = True
        all_dates_close = True

        for tx in group_txs[1:]:
            if not _merchants_match(first_tx.merchant, tx.merchant):
                all_merchants_match = False
            if not _amounts_match(first_tx.amount, tx.amount, amount_tolerance):
                all_amounts_match = False
            if not _dates_within_window(first_tx.tx_date, tx.tx_date, time_window_hours):
                all_dates_close = False

        # Build evidence and adjust confidence
        if all_merchants_match and first_tx.merchant:
            evidence.append(
                EvidenceItem(
                    evidence_type="merchant_pattern",
                    value=first_tx.merchant,
                    weight=0.3,
                    description=f"All transactions have same merchant: {first_tx.merchant}",
                )
            )
            confidence += 0.20

        if all_amounts_match:
            evidence.append(
                EvidenceItem(
                    evidence_type="amount_pattern",
                    value=first_tx.amount,
                    weight=0.3,
                    description=f"All transactions have identical amount: ${first_tx.amount:.2f}",
                )
            )
            confidence += 0.20

        if all_dates_close:
            evidence.append(
                EvidenceItem(
                    evidence_type="time_proximity",
                    value=time_window_hours,
                    weight=0.2,
                    description=f"All transactions within {time_window_hours}-hour window",
                )
            )
            confidence += 0.10

        # Add duplicate signal evidence
        evidence.append(
            EvidenceItem(
                evidence_type="duplicate_signal",
                value=identity_hash,
                weight=0.2,
                description=f"Identity hash match: {identity_hash}",
            )
        )

        # Cap confidence at 0.95 (never 100% certain)
        confidence = min(confidence, 0.95)

        # Determine explanation
        if confidence >= 0.85:
            explanation = (
                f"High confidence duplicate: {len(group_txs)} transactions with "
                f"matching merchant, amount (${first_tx.amount:.2f}), and close dates"
            )
        else:
            explanation = (
                f"Potential duplicate: {len(group_txs)} transactions share similar "
                f"characteristics but require review"
            )

        duplicate_groups.append(
            DuplicateGroup(
                group_id=f"dup_{uuid4().hex[:12]}",
                transaction_ids=[tx.transaction_id for tx in group_txs],
                confidence=confidence,
                explanation=explanation,
                evidence=evidence,
                requires_review=True,  # Duplicates always require human review
                detected_at=datetime.utcnow().isoformat(),
            )
        )

    return duplicate_groups
