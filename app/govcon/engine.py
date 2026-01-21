# app/govcon/engine.py
"""
GovCon Compliance Engine (Phase 2)

Core engine for DCAA-compliant transaction classification.
Persists results to separate tables (NO writes to source transactions).

CANONICAL LAWS:
- Backend is source of truth
- No polling, no background jobs
- Manual-run only
- Immutable audit logging
- Evidence chain required per FAR
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
from uuid import uuid4

from app.govcon.models import (
    GovConClassification,
    EvidenceChainItem,
    GovConTransactionOverlay,
    ExportPreviewItem,
    CostPoolType,
    AllowabilityStatus,
)
from app.govcon.rules import determine_allowability, determine_cost_pool


class GovConComplianceEngine:
    """
    Engine for GovCon / DCAA compliance operations.

    All operations are:
    - Manual-run only (no auto-triggers)
    - Non-destructive (writes to separate tables only)
    - Audit-logged with evidence chain
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        """Create GovCon compliance tables if they don't exist."""
        with sqlite3.connect(self.db_path) as conn:
            # GovCon classifications (read-only overlay)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS govcon_classifications (
                    id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    transaction_id TEXT NOT NULL,
                    allowability TEXT NOT NULL,
                    far_citation TEXT,
                    allowability_notes TEXT,
                    cost_pool TEXT NOT NULL,
                    cost_pool_notes TEXT,
                    intelligence_classification_id TEXT,
                    requires_review INTEGER NOT NULL DEFAULT 1,
                    reviewed_by TEXT,
                    reviewed_at TEXT,
                    classified_by TEXT NOT NULL,
                    classified_at TEXT NOT NULL,
                    UNIQUE(organization_id, transaction_id, classified_at)
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_govcon_cls_org ON govcon_classifications(organization_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_govcon_cls_tx ON govcon_classifications(transaction_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_govcon_cls_allow ON govcon_classifications(allowability)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_govcon_cls_pool ON govcon_classifications(cost_pool)"
            )

            # Evidence chain (immutable, hash-linked)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS govcon_evidence_chain (
                    id TEXT PRIMARY KEY,
                    classification_id TEXT NOT NULL,
                    evidence_type TEXT NOT NULL,
                    value TEXT NOT NULL,
                    description TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    prev_hash TEXT,
                    evidence_hash TEXT NOT NULL,
                    FOREIGN KEY (classification_id) REFERENCES govcon_classifications(id)
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_govcon_ev_cls ON govcon_evidence_chain(classification_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_govcon_ev_type ON govcon_evidence_chain(evidence_type)"
            )

            conn.commit()

    def _compute_evidence_hash(
        self,
        prev_hash: Optional[str],
        evidence_type: str,
        value: Any,
        description: str,
        created_at: str,
        created_by: str,
    ) -> str:
        """Compute deterministic hash for evidence chain integrity."""
        data = {
            "prev_hash": prev_hash or "",
            "evidence_type": evidence_type,
            "value": json.dumps(value, sort_keys=True),
            "description": description,
            "created_at": created_at,
            "created_by": created_by,
        }
        canonical = json.dumps(data, sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def _get_last_evidence_hash(self, classification_id: str) -> Optional[str]:
        """Get the hash of the most recent evidence item for chain continuity."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT evidence_hash FROM govcon_evidence_chain
                WHERE classification_id = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (classification_id,),
            ).fetchone()
            return row["evidence_hash"] if row else None

    def classify_transactions(
        self,
        org_id: str,
        user_id: str,
        transaction_ids: List[str],
    ) -> Tuple[List[GovConClassification], str]:
        """
        Classify transactions for GovCon / DCAA compliance.

        Args:
            org_id: Organization ID (for scoping)
            user_id: User ID (for audit)
            transaction_ids: List of transaction IDs to classify

        Returns:
            (classifications, audit_event_id)
        """
        now = datetime.utcnow().isoformat()
        audit_event_id = str(uuid4())

        # Fetch transactions from source table
        transactions = self._fetch_transactions(org_id, transaction_ids)

        if not transactions:
            return [], audit_event_id

        classifications: List[GovConClassification] = []

        for tx in transactions:
            tx_id = tx["id"]
            merchant = tx.get("merchant")
            description = tx.get("description", "")
            amount = tx.get("amount", 0.0)
            original_category = tx.get("original_category")

            # Check for existing Phase 1 intelligence classification
            intel_cls = self._get_intelligence_classification(org_id, tx_id)
            intel_category = intel_cls.get("category") if intel_cls else None

            # Determine allowability (FAR 31.201)
            allowability, far_citation, allow_notes, allow_rules = determine_allowability(
                merchant, description, intel_category or original_category
            )

            # Determine cost pool (CAS 418)
            cost_pool, pool_notes, pool_rules = determine_cost_pool(
                merchant, description, intel_category or original_category, amount
            )

            # Create classification
            cls_id = str(uuid4())
            requires_review = (
                allowability in ("pending_review", "requires_evidence", "partially_allowable")
                or cost_pool == "unallocated"
            )

            classification = GovConClassification(
                id=cls_id,
                organization_id=org_id,
                transaction_id=tx_id,
                allowability=allowability,
                far_citation=far_citation,
                allowability_notes=allow_notes,
                cost_pool=cost_pool,
                cost_pool_notes=pool_notes,
                intelligence_classification_id=intel_cls.get("id") if intel_cls else None,
                requires_review=requires_review,
                classified_by=user_id,
                classified_at=now,
                evidence_chain=[],
            )
            classifications.append(classification)

        # Persist classifications and evidence
        self._persist_classifications(org_id, user_id, classifications)

        return classifications, audit_event_id

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

    def _get_intelligence_classification(
        self, org_id: str, transaction_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get Phase 1 intelligence classification if exists (read-only)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT id, category, confidence, explanation
                FROM transaction_classifications
                WHERE organization_id = ? AND transaction_id = ?
                ORDER BY classified_at DESC LIMIT 1
                """,
                (org_id, transaction_id),
            ).fetchone()

        return dict(row) if row else None

    def _persist_classifications(
        self,
        org_id: str,
        user_id: str,
        classifications: List[GovConClassification],
    ) -> None:
        """Persist GovCon classifications and evidence chains."""
        if not classifications:
            return

        now = datetime.utcnow().isoformat()

        with sqlite3.connect(self.db_path) as conn:
            for cls in classifications:
                # Insert classification
                conn.execute(
                    """
                    INSERT INTO govcon_classifications
                        (id, organization_id, transaction_id, allowability, far_citation,
                         allowability_notes, cost_pool, cost_pool_notes,
                         intelligence_classification_id, requires_review,
                         classified_by, classified_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cls.id,
                        org_id,
                        cls.transaction_id,
                        cls.allowability,
                        cls.far_citation,
                        cls.allowability_notes,
                        cls.cost_pool,
                        cls.cost_pool_notes,
                        cls.intelligence_classification_id,
                        1 if cls.requires_review else 0,
                        user_id,
                        cls.classified_at,
                    ),
                )

                # Build evidence chain
                prev_hash = None

                # Evidence: FAR citation
                if cls.far_citation and cls.far_citation != "NONE":
                    ev_hash = self._compute_evidence_hash(
                        prev_hash, "far_citation", cls.far_citation,
                        f"FAR citation: {cls.far_citation}", now, user_id
                    )
                    conn.execute(
                        """
                        INSERT INTO govcon_evidence_chain
                            (id, classification_id, evidence_type, value, description,
                             created_at, created_by, prev_hash, evidence_hash)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(uuid4()),
                            cls.id,
                            "far_citation",
                            json.dumps(cls.far_citation),
                            f"FAR citation: {cls.far_citation}",
                            now,
                            user_id,
                            prev_hash,
                            ev_hash,
                        ),
                    )
                    prev_hash = ev_hash

                # Evidence: Allowability determination
                ev_hash = self._compute_evidence_hash(
                    prev_hash, "allowability_determination", cls.allowability,
                    cls.allowability_notes or "Allowability determined", now, user_id
                )
                conn.execute(
                    """
                    INSERT INTO govcon_evidence_chain
                        (id, classification_id, evidence_type, value, description,
                         created_at, created_by, prev_hash, evidence_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        cls.id,
                        "allowability_determination",
                        json.dumps(cls.allowability),
                        cls.allowability_notes or "Allowability determined",
                        now,
                        user_id,
                        prev_hash,
                        ev_hash,
                    ),
                )
                prev_hash = ev_hash

                # Evidence: Cost pool assignment
                ev_hash = self._compute_evidence_hash(
                    prev_hash, "cost_pool_assignment", cls.cost_pool,
                    cls.cost_pool_notes or "Cost pool assigned", now, user_id
                )
                conn.execute(
                    """
                    INSERT INTO govcon_evidence_chain
                        (id, classification_id, evidence_type, value, description,
                         created_at, created_by, prev_hash, evidence_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        cls.id,
                        "cost_pool_assignment",
                        json.dumps(cls.cost_pool),
                        cls.cost_pool_notes or "Cost pool assigned",
                        now,
                        user_id,
                        prev_hash,
                        ev_hash,
                    ),
                )
                prev_hash = ev_hash

                # Evidence: Intelligence link (if exists)
                if cls.intelligence_classification_id:
                    ev_hash = self._compute_evidence_hash(
                        prev_hash, "intelligence_link", cls.intelligence_classification_id,
                        "Linked to Phase 1 intelligence classification", now, user_id
                    )
                    conn.execute(
                        """
                        INSERT INTO govcon_evidence_chain
                            (id, classification_id, evidence_type, value, description,
                             created_at, created_by, prev_hash, evidence_hash)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(uuid4()),
                            cls.id,
                            "intelligence_link",
                            json.dumps(cls.intelligence_classification_id),
                            "Linked to Phase 1 intelligence classification",
                            now,
                            user_id,
                            prev_hash,
                            ev_hash,
                        ),
                    )

            conn.commit()

    def get_transactions_with_overlay(
        self,
        org_id: str,
        limit: int = 50,
        offset: int = 0,
        allowability_filter: Optional[AllowabilityStatus] = None,
        cost_pool_filter: Optional[CostPoolType] = None,
        only_pending_review: bool = False,
    ) -> Tuple[List[GovConTransactionOverlay], int]:
        """
        Get transactions with GovCon compliance overlay (read-only join).

        Args:
            org_id: Organization ID
            limit: Max results
            offset: Pagination offset
            allowability_filter: Filter by allowability status
            cost_pool_filter: Filter by cost pool
            only_pending_review: Only return items requiring review

        Returns:
            (transactions_with_overlay, total_count)
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Build query with optional filters
            base_query = """
                SELECT
                    t.id as transaction_id,
                    t.tx_date,
                    t.amount,
                    t.description,
                    t.merchant,
                    t.original_category,
                    ic.category as intel_category,
                    ic.confidence as intel_confidence,
                    gc.id as govcon_id,
                    gc.allowability,
                    gc.far_citation,
                    gc.allowability_notes,
                    gc.cost_pool,
                    gc.cost_pool_notes,
                    gc.intelligence_classification_id,
                    gc.requires_review,
                    gc.reviewed_by,
                    gc.reviewed_at,
                    gc.classified_by,
                    gc.classified_at
                FROM mvp_transactions t
                LEFT JOIN (
                    SELECT *,
                           ROW_NUMBER() OVER (
                               PARTITION BY transaction_id
                               ORDER BY classified_at DESC
                           ) as rn
                    FROM transaction_classifications
                    WHERE organization_id = ?
                ) ic ON t.id = ic.transaction_id AND ic.rn = 1
                LEFT JOIN (
                    SELECT *,
                           ROW_NUMBER() OVER (
                               PARTITION BY transaction_id
                               ORDER BY classified_at DESC
                           ) as rn
                    FROM govcon_classifications
                    WHERE organization_id = ?
                ) gc ON t.id = gc.transaction_id AND gc.rn = 1
                WHERE t.organization_id = ?
            """

            params = [org_id, org_id, org_id]

            if allowability_filter:
                base_query += " AND gc.allowability = ?"
                params.append(allowability_filter)

            if cost_pool_filter:
                base_query += " AND gc.cost_pool = ?"
                params.append(cost_pool_filter)

            if only_pending_review:
                base_query += " AND gc.requires_review = 1"

            # Count query
            count_query = f"SELECT COUNT(*) as cnt FROM ({base_query})"
            total = conn.execute(count_query, params).fetchone()["cnt"]

            # Data query with pagination
            data_query = f"{base_query} ORDER BY t.tx_date DESC LIMIT ? OFFSET ?"
            rows = conn.execute(data_query, params + [limit, offset]).fetchall()

        # PHASE 4 OPTIMIZATION: Batch fetch evidence chains to eliminate N+1 queries
        govcon_ids = [row["govcon_id"] for row in rows if row["govcon_id"]]
        evidence_by_govcon = self._batch_get_evidence_chains(govcon_ids)

        # Build response
        results: List[GovConTransactionOverlay] = []
        for row in rows:
            govcon_classification = None
            if row["govcon_id"]:
                # Use pre-fetched evidence (O(1) lookup)
                evidence_chain = evidence_by_govcon.get(row["govcon_id"], [])
                govcon_classification = GovConClassification(
                    id=row["govcon_id"],
                    organization_id=org_id,
                    transaction_id=row["transaction_id"],
                    allowability=row["allowability"],
                    far_citation=row["far_citation"],
                    allowability_notes=row["allowability_notes"],
                    cost_pool=row["cost_pool"],
                    cost_pool_notes=row["cost_pool_notes"],
                    intelligence_classification_id=row["intelligence_classification_id"],
                    requires_review=bool(row["requires_review"]),
                    reviewed_by=row["reviewed_by"],
                    reviewed_at=row["reviewed_at"],
                    classified_by=row["classified_by"],
                    classified_at=row["classified_at"],
                    evidence_chain=evidence_chain,
                )

            results.append(
                GovConTransactionOverlay(
                    transaction_id=row["transaction_id"],
                    tx_date=row["tx_date"],
                    amount=row["amount"],
                    description=row["description"],
                    merchant=row["merchant"],
                    original_category=row["original_category"],
                    intelligence_category=row["intel_category"],
                    intelligence_confidence=row["intel_confidence"],
                    govcon_classification=govcon_classification,
                    has_govcon_classification=govcon_classification is not None,
                    dcaa_compliant=(
                        govcon_classification is not None
                        and govcon_classification.allowability != "pending_review"
                        and govcon_classification.cost_pool != "unallocated"
                    ),
                    requires_review=(
                        govcon_classification.requires_review if govcon_classification else True
                    ),
                    evidence_complete=(
                        len(govcon_classification.evidence_chain) >= 2 if govcon_classification else False
                    ),
                )
            )

        return results, total

    def _get_evidence_chain(self, classification_id: str) -> List[EvidenceChainItem]:
        """Fetch evidence chain for a GovCon classification (single ID - legacy method)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, evidence_type, value, description, created_at, created_by,
                       prev_hash, evidence_hash
                FROM govcon_evidence_chain
                WHERE classification_id = ?
                ORDER BY created_at ASC
                """,
                (classification_id,),
            ).fetchall()

        return [
            EvidenceChainItem(
                id=row["id"],
                evidence_type=row["evidence_type"],
                value=json.loads(row["value"]),
                description=row["description"],
                created_at=row["created_at"],
                created_by=row["created_by"],
                prev_hash=row["prev_hash"],
                evidence_hash=row["evidence_hash"],
            )
            for row in rows
        ]

    def _batch_get_evidence_chains(
        self, classification_ids: List[str]
    ) -> Dict[str, List[EvidenceChainItem]]:
        """
        PHASE 4 OPTIMIZATION: Batch fetch evidence chains for multiple classifications.
        Eliminates N+1 query pattern by fetching all evidence in one query.
        """
        if not classification_ids:
            return {}

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            placeholders = ",".join("?" * len(classification_ids))
            rows = conn.execute(
                f"""
                SELECT classification_id, id, evidence_type, value, description,
                       created_at, created_by, prev_hash, evidence_hash
                FROM govcon_evidence_chain
                WHERE classification_id IN ({placeholders})
                ORDER BY classification_id, created_at ASC
                """,
                classification_ids,
            ).fetchall()

        # Group by classification_id
        result: Dict[str, List[EvidenceChainItem]] = {}
        for row in rows:
            cls_id = row["classification_id"]
            if cls_id not in result:
                result[cls_id] = []
            result[cls_id].append(
                EvidenceChainItem(
                    id=row["id"],
                    evidence_type=row["evidence_type"],
                    value=json.loads(row["value"]),
                    description=row["description"],
                    created_at=row["created_at"],
                    created_by=row["created_by"],
                    prev_hash=row["prev_hash"],
                    evidence_hash=row["evidence_hash"],
                )
            )
        return result

    def generate_export_preview(
        self,
        org_id: str,
        user_id: str,
        transaction_ids: Optional[List[str]] = None,
    ) -> Tuple[List[ExportPreviewItem], Dict[str, Any], List[str]]:
        """
        Generate export preview for DCAA submission (NO auto-export).

        Args:
            org_id: Organization ID
            user_id: User ID (for audit)
            transaction_ids: Optional list of specific transaction IDs

        Returns:
            (preview_items, summary, blocking_issues)
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Query GovCon classified transactions
            if transaction_ids:
                placeholders = ",".join("?" * len(transaction_ids))
                query = f"""
                    SELECT
                        t.id as transaction_id,
                        t.tx_date,
                        t.amount,
                        t.description,
                        gc.cost_pool,
                        gc.allowability,
                        gc.far_citation,
                        gc.requires_review,
                        (SELECT COUNT(*) FROM govcon_evidence_chain WHERE classification_id = gc.id) as evidence_count
                    FROM mvp_transactions t
                    JOIN govcon_classifications gc ON t.id = gc.transaction_id
                        AND gc.organization_id = t.organization_id
                    WHERE t.organization_id = ? AND t.id IN ({placeholders})
                    ORDER BY t.tx_date DESC
                """
                params = [org_id] + transaction_ids
            else:
                query = """
                    SELECT
                        t.id as transaction_id,
                        t.tx_date,
                        t.amount,
                        t.description,
                        gc.cost_pool,
                        gc.allowability,
                        gc.far_citation,
                        gc.requires_review,
                        (SELECT COUNT(*) FROM govcon_evidence_chain WHERE classification_id = gc.id) as evidence_count
                    FROM mvp_transactions t
                    JOIN (
                        SELECT *,
                               ROW_NUMBER() OVER (PARTITION BY transaction_id ORDER BY classified_at DESC) as rn
                        FROM govcon_classifications
                        WHERE organization_id = ?
                    ) gc ON t.id = gc.transaction_id AND gc.rn = 1
                    WHERE t.organization_id = ?
                    ORDER BY t.tx_date DESC
                """
                params = [org_id, org_id]

            rows = conn.execute(query, params).fetchall()

        # Build preview items
        preview: List[ExportPreviewItem] = []
        blocking_issues: List[str] = []

        total_amount = 0.0
        allowable_amount = 0.0
        unallowable_amount = 0.0
        pending_count = 0

        for row in rows:
            dcaa_compliant = (
                row["allowability"] != "pending_review"
                and row["cost_pool"] != "unallocated"
                and row["evidence_count"] >= 2
            )

            preview.append(
                ExportPreviewItem(
                    transaction_id=row["transaction_id"],
                    tx_date=row["tx_date"],
                    amount=row["amount"],
                    description=row["description"],
                    cost_pool=row["cost_pool"],
                    allowability=row["allowability"],
                    far_citation=row["far_citation"],
                    evidence_count=row["evidence_count"],
                    dcaa_compliant=dcaa_compliant,
                )
            )

            total_amount += row["amount"]
            if row["allowability"] == "allowable":
                allowable_amount += row["amount"]
            elif row["allowability"] == "unallowable":
                unallowable_amount += row["amount"]
            elif row["allowability"] == "pending_review":
                pending_count += 1

            # Check for blocking issues
            if row["requires_review"]:
                blocking_issues.append(f"Transaction {row['transaction_id']} requires review")
            if row["evidence_count"] < 2:
                blocking_issues.append(f"Transaction {row['transaction_id']} has insufficient evidence")

        summary = {
            "total_transactions": len(preview),
            "total_amount": total_amount,
            "allowable_amount": allowable_amount,
            "unallowable_amount": unallowable_amount,
            "pending_review_count": pending_count,
            "dcaa_compliant_count": sum(1 for p in preview if p.dcaa_compliant),
            "by_cost_pool": {},
            "by_allowability": {},
        }

        # Group by cost pool
        for item in preview:
            pool = item.cost_pool
            if pool not in summary["by_cost_pool"]:
                summary["by_cost_pool"][pool] = {"count": 0, "amount": 0.0}
            summary["by_cost_pool"][pool]["count"] += 1
            summary["by_cost_pool"][pool]["amount"] += item.amount

        # Group by allowability
        for item in preview:
            status = item.allowability
            if status not in summary["by_allowability"]:
                summary["by_allowability"][status] = {"count": 0, "amount": 0.0}
            summary["by_allowability"][status]["count"] += 1
            summary["by_allowability"][status]["amount"] += item.amount

        return preview, summary, blocking_issues
