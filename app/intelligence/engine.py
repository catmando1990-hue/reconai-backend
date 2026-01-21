# app/intelligence/engine.py
"""
Transaction Intelligence Engine (Phase 1)

Core engine for transaction classification and duplicate detection.
Persists results to separate tables (NO writes to source transactions).

CANONICAL LAWS:
- Backend is source of truth
- No polling, no background jobs
- Manual-run only
- Immutable audit logging
- Confidence < 0.85 flagged for review
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
from uuid import uuid4

from app.intelligence.models import (
    ClassificationResult,
    EvidenceItem,
    DuplicateGroup,
    TransactionWithClassification,
)
from app.intelligence.rules import classify_transaction
from app.intelligence.duplicates import detect_duplicates, TransactionData


# Confidence threshold for flagging review
CONFIDENCE_THRESHOLD = 0.85


class TransactionIntelligenceEngine:
    """
    Engine for transaction intelligence operations.

    All operations are:
    - Manual-run only (no auto-triggers)
    - Non-destructive (writes to separate tables only)
    - Audit-logged
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        """Create intelligence tables if they don't exist."""
        with sqlite3.connect(self.db_path) as conn:
            # Transaction classifications (read-only overlay)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS transaction_classifications (
                    id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    transaction_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    explanation TEXT NOT NULL,
                    matched_rules TEXT NOT NULL DEFAULT '[]',
                    requires_review INTEGER NOT NULL DEFAULT 0,
                    classified_by TEXT NOT NULL,
                    classified_at TEXT NOT NULL,
                    superseded_by TEXT,
                    superseded_at TEXT,
                    UNIQUE(organization_id, transaction_id, classified_at)
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tc_org ON transaction_classifications(organization_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tc_tx ON transaction_classifications(transaction_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tc_review ON transaction_classifications(requires_review)"
            )

            # Transaction evidence (supporting data for classifications)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS transaction_evidence (
                    id TEXT PRIMARY KEY,
                    classification_id TEXT NOT NULL,
                    evidence_type TEXT NOT NULL,
                    value TEXT NOT NULL,
                    weight REAL NOT NULL,
                    description TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (classification_id) REFERENCES transaction_classifications(id)
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_te_classification ON transaction_evidence(classification_id)"
            )

            # Duplicate detection results
            conn.execute("""
                CREATE TABLE IF NOT EXISTS transaction_duplicates (
                    id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    group_id TEXT NOT NULL,
                    transaction_ids TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    explanation TEXT NOT NULL,
                    detected_by TEXT NOT NULL,
                    detected_at TEXT NOT NULL,
                    resolved INTEGER NOT NULL DEFAULT 0,
                    resolved_by TEXT,
                    resolved_at TEXT,
                    resolution_note TEXT
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_td_org ON transaction_duplicates(organization_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_td_group ON transaction_duplicates(group_id)"
            )

            # Duplicate evidence
            conn.execute("""
                CREATE TABLE IF NOT EXISTS duplicate_evidence (
                    id TEXT PRIMARY KEY,
                    duplicate_id TEXT NOT NULL,
                    evidence_type TEXT NOT NULL,
                    value TEXT NOT NULL,
                    weight REAL NOT NULL,
                    description TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (duplicate_id) REFERENCES transaction_duplicates(id)
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_de_duplicate ON duplicate_evidence(duplicate_id)"
            )

            conn.commit()

    def classify_transactions(
        self,
        org_id: str,
        user_id: str,
        transaction_ids: List[str],
    ) -> Tuple[List[ClassificationResult], List[DuplicateGroup], str]:
        """
        Classify transactions and detect duplicates.

        Args:
            org_id: Organization ID (for scoping)
            user_id: User ID (for audit)
            transaction_ids: List of transaction IDs to classify

        Returns:
            (classifications, duplicates, audit_event_id)
        """
        now = datetime.utcnow().isoformat()
        audit_event_id = str(uuid4())

        # Fetch transactions from source table
        transactions = self._fetch_transactions(org_id, transaction_ids)

        if not transactions:
            return [], [], audit_event_id

        # Classify each transaction
        classifications: List[ClassificationResult] = []
        tx_data_list: List[TransactionData] = []

        for tx in transactions:
            tx_id = tx["id"]
            merchant = tx.get("merchant")
            description = tx.get("description", "")
            amount = tx.get("amount", 0.0)

            # Classify using rules engine
            category, confidence, explanation, evidence, matched_rules = classify_transaction(
                tx_id, merchant, description, amount
            )

            requires_review = confidence < CONFIDENCE_THRESHOLD or category == "uncertain"

            classification = ClassificationResult(
                transaction_id=tx_id,
                category=category,
                confidence=confidence,
                explanation=explanation,
                evidence=evidence,
                requires_review=requires_review,
                matched_rules=matched_rules,
                classified_at=now,
            )
            classifications.append(classification)

            # Prepare for duplicate detection
            tx_data_list.append(
                TransactionData(
                    transaction_id=tx_id,
                    tx_date=tx.get("tx_date"),
                    amount=amount,
                    description=description,
                    merchant=merchant,
                )
            )

        # Detect duplicates
        duplicates = detect_duplicates(tx_data_list)

        # Persist results to separate tables
        self._persist_classifications(org_id, user_id, classifications)
        self._persist_duplicates(org_id, user_id, duplicates)

        return classifications, duplicates, audit_event_id

    def _fetch_transactions(
        self, org_id: str, transaction_ids: List[str]
    ) -> List[Dict[str, Any]]:
        """Fetch transactions from source table (read-only)."""
        if not transaction_ids:
            return []

        placeholders = ",".join("?" * len(transaction_ids))
        query = f"""
            SELECT id, tx_date, amount, description, merchant, original_category
            FROM mvp_transactions
            WHERE organization_id = ? AND id IN ({placeholders})
        """

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, [org_id] + transaction_ids).fetchall()

        return [dict(row) for row in rows]

    def _persist_classifications(
        self,
        org_id: str,
        user_id: str,
        classifications: List[ClassificationResult],
    ) -> None:
        """Persist classification results to overlay table."""
        if not classifications:
            return

        with sqlite3.connect(self.db_path) as conn:
            for cls in classifications:
                cls_id = str(uuid4())

                # Insert classification
                conn.execute(
                    """
                    INSERT INTO transaction_classifications
                        (id, organization_id, transaction_id, category, confidence,
                         explanation, matched_rules, requires_review, classified_by, classified_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cls_id,
                        org_id,
                        cls.transaction_id,
                        cls.category,
                        cls.confidence,
                        cls.explanation,
                        json.dumps(cls.matched_rules),
                        1 if cls.requires_review else 0,
                        user_id,
                        cls.classified_at,
                    ),
                )

                # Insert evidence
                for ev in cls.evidence:
                    conn.execute(
                        """
                        INSERT INTO transaction_evidence
                            (id, classification_id, evidence_type, value, weight, description, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(uuid4()),
                            cls_id,
                            ev.evidence_type,
                            json.dumps(ev.value),
                            ev.weight,
                            ev.description,
                            cls.classified_at,
                        ),
                    )

            conn.commit()

    def _persist_duplicates(
        self,
        org_id: str,
        user_id: str,
        duplicates: List[DuplicateGroup],
    ) -> None:
        """Persist duplicate detection results."""
        if not duplicates:
            return

        with sqlite3.connect(self.db_path) as conn:
            for dup in duplicates:
                dup_id = str(uuid4())

                # Insert duplicate group
                conn.execute(
                    """
                    INSERT INTO transaction_duplicates
                        (id, organization_id, group_id, transaction_ids, confidence,
                         explanation, detected_by, detected_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        dup_id,
                        org_id,
                        dup.group_id,
                        json.dumps(dup.transaction_ids),
                        dup.confidence,
                        dup.explanation,
                        user_id,
                        dup.detected_at,
                    ),
                )

                # Insert evidence
                for ev in dup.evidence:
                    conn.execute(
                        """
                        INSERT INTO duplicate_evidence
                            (id, duplicate_id, evidence_type, value, weight, description, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(uuid4()),
                            dup_id,
                            ev.evidence_type,
                            json.dumps(ev.value),
                            ev.weight,
                            ev.description,
                            dup.detected_at,
                        ),
                    )

            conn.commit()

    def get_transactions_with_overlay(
        self,
        org_id: str,
        limit: int = 50,
        offset: int = 0,
        only_flagged: bool = False,
    ) -> Tuple[List[TransactionWithClassification], int]:
        """
        Get transactions with their classification overlay (read-only join).

        Args:
            org_id: Organization ID
            limit: Max results
            offset: Pagination offset
            only_flagged: If True, only return transactions requiring review

        Returns:
            (transactions_with_overlay, total_count)
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Base query with LEFT JOIN to overlay tables
            base_query = """
                SELECT
                    t.id as transaction_id,
                    t.tx_date,
                    t.amount,
                    t.description,
                    t.merchant,
                    t.original_category,
                    c.id as classification_id,
                    c.category,
                    c.confidence,
                    c.explanation,
                    c.matched_rules,
                    c.requires_review,
                    c.classified_at,
                    d.group_id as duplicate_group_id,
                    d.transaction_ids as duplicate_tx_ids,
                    d.confidence as duplicate_confidence,
                    d.explanation as duplicate_explanation
                FROM mvp_transactions t
                LEFT JOIN (
                    SELECT *,
                           ROW_NUMBER() OVER (
                               PARTITION BY transaction_id
                               ORDER BY classified_at DESC
                           ) as rn
                    FROM transaction_classifications
                    WHERE organization_id = ?
                ) c ON t.id = c.transaction_id AND c.rn = 1
                LEFT JOIN transaction_duplicates d
                    ON d.organization_id = ?
                    AND d.transaction_ids LIKE '%' || t.id || '%'
                    AND d.resolved = 0
                WHERE t.organization_id = ?
            """

            params = [org_id, org_id, org_id]

            if only_flagged:
                base_query += " AND (c.requires_review = 1 OR d.id IS NOT NULL)"

            # Count query
            count_query = f"SELECT COUNT(*) as cnt FROM ({base_query})"
            total = conn.execute(count_query, params).fetchone()["cnt"]

            # Data query with pagination
            data_query = f"{base_query} ORDER BY t.tx_date DESC LIMIT ? OFFSET ?"
            rows = conn.execute(data_query, params + [limit, offset]).fetchall()

        # Build response
        results: List[TransactionWithClassification] = []
        for row in rows:
            classification = None
            if row["classification_id"]:
                # Fetch evidence for this classification
                evidence = self._get_classification_evidence(row["classification_id"])
                classification = ClassificationResult(
                    transaction_id=row["transaction_id"],
                    category=row["category"],
                    confidence=row["confidence"],
                    explanation=row["explanation"],
                    evidence=evidence,
                    requires_review=bool(row["requires_review"]),
                    matched_rules=json.loads(row["matched_rules"] or "[]"),
                    classified_at=row["classified_at"],
                )

            duplicate_group = None
            if row["duplicate_group_id"]:
                # Fetch evidence for this duplicate group
                dup_evidence = self._get_duplicate_evidence_by_group(row["duplicate_group_id"])
                duplicate_group = DuplicateGroup(
                    group_id=row["duplicate_group_id"],
                    transaction_ids=json.loads(row["duplicate_tx_ids"] or "[]"),
                    confidence=row["duplicate_confidence"],
                    explanation=row["duplicate_explanation"],
                    evidence=dup_evidence,
                    requires_review=True,
                    detected_at=datetime.utcnow().isoformat(),
                )

            results.append(
                TransactionWithClassification(
                    transaction_id=row["transaction_id"],
                    tx_date=row["tx_date"],
                    amount=row["amount"],
                    description=row["description"],
                    merchant=row["merchant"],
                    original_category=row["original_category"],
                    classification=classification,
                    duplicate_group=duplicate_group,
                    has_classification=classification is not None,
                    last_classified_at=row["classified_at"],
                )
            )

        return results, total

    def _get_classification_evidence(self, classification_id: str) -> List[EvidenceItem]:
        """Fetch evidence for a classification."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT evidence_type, value, weight, description
                FROM transaction_evidence
                WHERE classification_id = ?
                """,
                (classification_id,),
            ).fetchall()

        return [
            EvidenceItem(
                evidence_type=row["evidence_type"],
                value=json.loads(row["value"]),
                weight=row["weight"],
                description=row["description"],
            )
            for row in rows
        ]

    def _get_duplicate_evidence_by_group(self, group_id: str) -> List[EvidenceItem]:
        """Fetch evidence for a duplicate group."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT e.evidence_type, e.value, e.weight, e.description
                FROM duplicate_evidence e
                JOIN transaction_duplicates d ON e.duplicate_id = d.id
                WHERE d.group_id = ?
                """,
                (group_id,),
            ).fetchall()

        return [
            EvidenceItem(
                evidence_type=row["evidence_type"],
                value=json.loads(row["value"]),
                weight=row["weight"],
                description=row["description"],
            )
            for row in rows
        ]

    def get_classification_stats(self, org_id: str) -> Dict[str, Any]:
        """Get classification statistics for an organization."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Total transactions
            total = conn.execute(
                "SELECT COUNT(*) as cnt FROM mvp_transactions WHERE organization_id = ?",
                (org_id,),
            ).fetchone()["cnt"]

            # Classified count
            classified = conn.execute(
                """
                SELECT COUNT(DISTINCT transaction_id) as cnt
                FROM transaction_classifications
                WHERE organization_id = ?
                """,
                (org_id,),
            ).fetchone()["cnt"]

            # Flagged for review
            flagged = conn.execute(
                """
                SELECT COUNT(DISTINCT transaction_id) as cnt
                FROM transaction_classifications
                WHERE organization_id = ? AND requires_review = 1
                """,
                (org_id,),
            ).fetchone()["cnt"]

            # Duplicate groups (unresolved)
            duplicates = conn.execute(
                """
                SELECT COUNT(*) as cnt
                FROM transaction_duplicates
                WHERE organization_id = ? AND resolved = 0
                """,
                (org_id,),
            ).fetchone()["cnt"]

        return {
            "total_transactions": total,
            "classified_count": classified,
            "unclassified_count": total - classified,
            "flagged_for_review": flagged,
            "duplicate_groups": duplicates,
        }
