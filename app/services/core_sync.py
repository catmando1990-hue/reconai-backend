# app/services/core_sync.py
"""
CORE Sync Orchestrator - Single source of truth for organization state.

This service orchestrates the complete CORE hydration pipeline:
1. Fetch Plaid transactions for org
2. Normalize merchants
3. Persist transactions
4. Derive CORE entities: invoices, bills, customers, vendors
5. Persist entities
6. Compute derived metrics
7. Update CORE sync metadata

CRITICAL RULES:
- Unknown values = null (NEVER 0)
- All metrics are derived from CORE entities (not independent queries)
- This is the ONLY service that performs entity derivation
- No background jobs - all operations are manual-triggered
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from app.db import DB_PATH
from app.services.plaid_service import PlaidService, get_plaid_service

logger = logging.getLogger(__name__)


# =============================================================================
# CORE STATE MODELS
# =============================================================================


# Staleness threshold (24 hours)
STALE_THRESHOLD_HOURS = 24


@dataclass
class CoreSyncMetadata:
    """
    Tracks the last sync state for an organization.

    LIFECYCLE STATES:
    - 'never': No sync has ever been attempted
    - 'running': Sync is currently in progress (sync_started_at is set)
    - 'success': Last sync completed successfully (is_full_success=True)
    - 'failed': Last sync failed or was partial

    CRITICAL:
    - sync_started_at: Set immediately when sync begins, cleared on completion
    - last_successful_sync_at: ONLY set on FULL successful sync (never partial)
    """
    organization_id: str
    sync_started_at: Optional[datetime]  # Set when sync begins, null when not running
    last_synced_at: Optional[datetime]
    last_successful_sync_at: Optional[datetime]  # ONLY set on FULL success
    last_sync_request_id: Optional[str]
    transactions_synced: Optional[int]
    entities_derived: Optional[int]
    sync_status: str  # 'never' | 'running' | 'success' | 'failed'
    error_message: Optional[str]
    last_retry_at: Optional[datetime]
    retry_count: int


@dataclass
class CoreMetrics:
    """
    Derived metrics from CORE entities.

    CRITICAL: Unknown values = null, NEVER 0.
    """
    # Transaction metrics (null if no data)
    total_transactions: Optional[int]
    total_income: Optional[float]
    total_expenses: Optional[float]
    net_cashflow: Optional[float]

    # Entity counts (null if no data)
    customer_count: Optional[int]
    vendor_count: Optional[int]
    invoice_count: Optional[int]
    bill_count: Optional[int]

    # AR/AP metrics (null if no data)
    ar_outstanding: Optional[float]
    ap_outstanding: Optional[float]

    # Connected accounts (null if no data)
    plaid_item_count: Optional[int]
    active_account_count: Optional[int]


@dataclass
class CoreState:
    """
    Complete CORE state for an organization.

    This is the SINGLE SOURCE OF TRUTH for dashboard data.
    All frontend metrics MUST come from this structure.
    """
    organization_id: str
    sync_metadata: CoreSyncMetadata
    metrics: CoreMetrics
    plaid_items: List[Dict[str, Any]]
    recent_transactions: List[Dict[str, Any]]
    # Entity summaries (not full lists)
    customer_summary: Optional[Dict[str, Any]]
    vendor_summary: Optional[Dict[str, Any]]
    invoice_summary: Optional[Dict[str, Any]]
    bill_summary: Optional[Dict[str, Any]]


# =============================================================================
# MERCHANT NORMALIZATION
# =============================================================================


class MerchantNormalizer:
    """
    Normalizes merchant names from Plaid transactions.

    Maps raw transaction names to canonical merchant names for
    consistent vendor/customer derivation.
    """

    # Common patterns to strip from merchant names
    STRIP_PATTERNS = [
        r'\s+#\d+',           # Store numbers: "WALMART #1234"
        r'\s+\d{4,}',         # Long numbers at end
        r'\s+\*+',            # Asterisks
        r'\s+[A-Z]{2}\s*$',   # State codes at end
        r'SQ\s*\*',           # Square prefix
        r'TST\s*\*',          # Toast prefix
        r'PAYPAL\s*\*',       # PayPal prefix
    ]

    # Known merchant mappings for consistency
    KNOWN_MERCHANTS = {
        'AMAZON': 'Amazon',
        'AMZN': 'Amazon',
        'WALMART': 'Walmart',
        'TARGET': 'Target',
        'UBER': 'Uber',
        'LYFT': 'Lyft',
        'STARBUCKS': 'Starbucks',
        'MCDONALDS': "McDonald's",
        'HOME DEPOT': 'Home Depot',
        'LOWES': "Lowe's",
    }

    def normalize(self, raw_name: str, merchant_name: Optional[str] = None) -> str:
        """
        Normalize a merchant name.

        Args:
            raw_name: The transaction name/description
            merchant_name: Optional Plaid-provided merchant name

        Returns:
            Normalized merchant name
        """
        # Prefer Plaid's merchant_name if available
        name = merchant_name or raw_name
        if not name:
            return "Unknown Merchant"

        # Uppercase for matching
        upper_name = name.upper().strip()

        # Check known merchants first
        for pattern, canonical in self.KNOWN_MERCHANTS.items():
            if pattern in upper_name:
                return canonical

        # Apply strip patterns
        cleaned = name
        for pattern in self.STRIP_PATTERNS:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)

        # Title case and strip
        cleaned = cleaned.strip().title()

        return cleaned if cleaned else "Unknown Merchant"


# =============================================================================
# ENTITY DERIVATION
# =============================================================================


class EntityDeriver:
    """
    Derives CORE entities from transactions.

    Creates vendors/customers based on transaction patterns.
    This is advisory-only - no automatic entity creation without user approval.
    """

    def __init__(self, normalizer: MerchantNormalizer):
        self.normalizer = normalizer

    def derive_vendor_suggestions(
        self,
        transactions: List[Dict[str, Any]],
        existing_vendors: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Suggest new vendors based on outgoing transactions.

        Args:
            transactions: List of transaction dicts with amount < 0
            existing_vendors: Currently tracked vendors

        Returns:
            List of vendor suggestions (not auto-created)
        """
        existing_names = {v.get('name', '').lower() for v in existing_vendors}

        # Group transactions by normalized merchant
        merchant_txns: Dict[str, List[Dict[str, Any]]] = {}
        for tx in transactions:
            # Negative amounts are outgoing (expenses)
            if tx.get('amount', 0) <= 0:
                continue

            merchant = self.normalizer.normalize(
                tx.get('name', ''),
                tx.get('merchant_name')
            )

            if merchant.lower() not in existing_names:
                if merchant not in merchant_txns:
                    merchant_txns[merchant] = []
                merchant_txns[merchant].append(tx)

        # Generate suggestions for merchants with multiple transactions
        suggestions = []
        for merchant, txns in merchant_txns.items():
            if len(txns) >= 2:  # At least 2 transactions to suggest
                total_amount = sum(float(tx.get('amount', 0)) for tx in txns)
                suggestions.append({
                    'suggested_name': merchant,
                    'transaction_count': len(txns),
                    'total_amount': total_amount,
                    'first_seen': min(tx.get('date', '') for tx in txns),
                    'last_seen': max(tx.get('date', '') for tx in txns),
                    'sample_transactions': txns[:3],  # First 3 for review
                })

        return sorted(suggestions, key=lambda x: x['total_amount'], reverse=True)

    def derive_customer_suggestions(
        self,
        transactions: List[Dict[str, Any]],
        existing_customers: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Suggest new customers based on incoming transactions.

        Args:
            transactions: List of transaction dicts with amount > 0
            existing_customers: Currently tracked customers

        Returns:
            List of customer suggestions (not auto-created)
        """
        existing_names = {c.get('name', '').lower() for c in existing_customers}

        # Group transactions by normalized merchant (incoming = potential customer)
        customer_txns: Dict[str, List[Dict[str, Any]]] = {}
        for tx in transactions:
            # Positive amounts are incoming (income)
            if tx.get('amount', 0) >= 0:
                continue

            merchant = self.normalizer.normalize(
                tx.get('name', ''),
                tx.get('merchant_name')
            )

            if merchant.lower() not in existing_names:
                if merchant not in customer_txns:
                    customer_txns[merchant] = []
                customer_txns[merchant].append(tx)

        # Generate suggestions
        suggestions = []
        for customer, txns in customer_txns.items():
            if len(txns) >= 1:  # Income sources are more significant
                total_amount = abs(sum(float(tx.get('amount', 0)) for tx in txns))
                suggestions.append({
                    'suggested_name': customer,
                    'transaction_count': len(txns),
                    'total_amount': total_amount,
                    'first_seen': min(tx.get('date', '') for tx in txns),
                    'last_seen': max(tx.get('date', '') for tx in txns),
                    'sample_transactions': txns[:3],
                })

        return sorted(suggestions, key=lambda x: x['total_amount'], reverse=True)


# =============================================================================
# CORE SYNC SERVICE
# =============================================================================


class CoreSyncService:
    """
    CORE Sync Orchestrator - Single source of truth for organization state.

    This service:
    1. Fetches transactions from all connected Plaid items
    2. Normalizes merchant data
    3. Persists transactions
    4. Derives entity suggestions (vendors, customers)
    5. Computes derived metrics
    6. Updates sync metadata

    CRITICAL: This is manual-only. No background jobs or polling.
    """

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.normalizer = MerchantNormalizer()
        self.deriver = EntityDeriver(self.normalizer)
        self._plaid_service: Optional[PlaidService] = None
        self._ensure_tables()

    @property
    def plaid_service(self) -> PlaidService:
        """Lazy-load Plaid service."""
        if self._plaid_service is None:
            self._plaid_service = get_plaid_service()
        return self._plaid_service

    def _get_conn(self) -> sqlite3.Connection:
        """Get database connection with row factory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_tables(self) -> None:
        """Ensure CORE sync tables exist."""
        with self._get_conn() as conn:
            # CORE sync metadata table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS core_sync_metadata (
                    id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL UNIQUE,
                    last_synced_at TEXT,
                    last_sync_request_id TEXT,
                    transactions_synced INTEGER,
                    entities_derived INTEGER,
                    sync_status TEXT DEFAULT 'idle',
                    error_message TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE
                )
            """)

            # CORE transactions table (persisted from Plaid)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS core_transactions (
                    id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    plaid_transaction_id TEXT UNIQUE,
                    plaid_item_id TEXT,
                    account_id TEXT,
                    amount REAL NOT NULL,
                    date TEXT NOT NULL,
                    name TEXT NOT NULL,
                    merchant_name TEXT,
                    merchant_normalized TEXT,
                    category TEXT,
                    category_id TEXT,
                    pending INTEGER DEFAULT 0,
                    payment_channel TEXT,
                    iso_currency_code TEXT DEFAULT 'USD',
                    transaction_type TEXT,
                    is_income INTEGER DEFAULT 0,
                    is_expense INTEGER DEFAULT 0,
                    linked_vendor_id TEXT,
                    linked_customer_id TEXT,
                    linked_invoice_id TEXT,
                    linked_bill_id TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE
                )
            """)

            # Indexes for CORE transactions
            conn.execute("CREATE INDEX IF NOT EXISTS idx_core_tx_org ON core_transactions(organization_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_core_tx_plaid_id ON core_transactions(plaid_transaction_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_core_tx_date ON core_transactions(date)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_core_tx_merchant ON core_transactions(merchant_normalized)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_core_tx_item ON core_transactions(plaid_item_id)")

            conn.commit()

    # =========================================================================
    # SYNC OPERATIONS
    # =========================================================================

    def sync_organization(
        self,
        organization_id: str,
        user_id: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Perform a full CORE sync for an organization.

        Pipeline:
        1. Fetch transactions from all Plaid items
        2. Normalize merchants
        3. Persist transactions
        4. Derive entity suggestions
        5. Compute metrics
        6. Update sync metadata

        Args:
            organization_id: The organization to sync
            user_id: The user triggering the sync
            ip_address: Client IP for audit
            user_agent: Client user agent for audit

        Returns:
            Sync result with metrics and any errors
        """
        request_id = f"core_{uuid4().hex[:16]}"

        try:
            # CRITICAL: Mark sync as running IMMEDIATELY
            # This sets sync_status='running' and sync_started_at=now()
            self._mark_sync_running(organization_id, request_id)

            # Step 1: Get all Plaid items for org
            items_response = self.plaid_service.list_items(organization_id)
            if not items_response.success:
                raise Exception(f"Failed to list Plaid items: {items_response.error}")

            plaid_items = items_response.items or []
            active_items = [i for i in plaid_items if i.status.value == 'active']

            if not active_items:
                # No active items - this is a valid success state (nothing to sync)
                self._update_sync_status(
                    organization_id, 'success', request_id,
                    transactions_synced=0, entities_derived=0,
                    is_full_success=True,
                )
                return {
                    'success': True,
                    'request_id': request_id,
                    'message': 'No active Plaid items to sync',
                    'transactions_synced': 0,
                    'plaid_items': len(plaid_items),
                    'active_items': 0,
                    'is_full_success': True,
                }

            # Step 2: Sync transactions from each item
            all_transactions = []
            sync_errors = []

            for item in active_items:
                try:
                    sync_response = self.plaid_service.sync_transactions(
                        organization_id=organization_id,
                        user_id=user_id,
                        item_id=item.item_id,
                        count=500,
                        ip_address=ip_address,
                        user_agent=user_agent,
                    )

                    if sync_response.success:
                        # Attach item_id to transactions
                        for tx in (sync_response.added or []):
                            tx_dict = tx.model_dump()
                            tx_dict['plaid_item_id'] = item.item_id
                            all_transactions.append(tx_dict)
                    else:
                        sync_errors.append({
                            'item_id': item.item_id,
                            'error': sync_response.error.model_dump() if sync_response.error else 'Unknown error'
                        })
                except Exception as e:
                    logger.exception(f"Error syncing item {item.item_id}: {e}")
                    sync_errors.append({
                        'item_id': item.item_id,
                        'error': str(e)
                    })

            # Step 3: Normalize and persist transactions
            persisted_count = self._persist_transactions(organization_id, all_transactions)

            # Step 4: Derive entity suggestions (advisory only)
            vendor_suggestions = self._derive_vendor_suggestions(organization_id)
            customer_suggestions = self._derive_customer_suggestions(organization_id)
            entities_derived = len(vendor_suggestions) + len(customer_suggestions)

            # Step 5: Update sync metadata
            # CRITICAL: Only mark as full success if NO sync errors occurred
            is_full_success = len(sync_errors) == 0
            self._update_sync_status(
                organization_id,
                'success' if is_full_success else 'failed',
                request_id,
                transactions_synced=persisted_count,
                entities_derived=entities_derived,
                error_message=f"Partial sync: {len(sync_errors)} items failed" if sync_errors else None,
                is_full_success=is_full_success,
            )

            return {
                'success': True,
                'request_id': request_id,
                'transactions_synced': persisted_count,
                'plaid_items': len(plaid_items),
                'active_items': len(active_items),
                'vendor_suggestions': len(vendor_suggestions),
                'customer_suggestions': len(customer_suggestions),
                'sync_errors': sync_errors if sync_errors else None,
                'is_full_success': is_full_success,
            }

        except Exception as e:
            logger.exception(f"CORE sync failed for org {organization_id}: {e}")
            self._update_sync_status(
                organization_id, 'failed', request_id,
                error_message=str(e),
                is_full_success=False,
            )
            return {
                'success': False,
                'request_id': request_id,
                'error': str(e),
            }

    def _persist_transactions(
        self,
        organization_id: str,
        transactions: List[Dict[str, Any]],
    ) -> int:
        """
        Persist transactions to CORE transactions table.

        Uses upsert to handle duplicates gracefully.

        Returns:
            Number of transactions persisted
        """
        if not transactions:
            return 0

        persisted = 0
        with self._get_conn() as conn:
            for tx in transactions:
                # Normalize merchant
                merchant_normalized = self.normalizer.normalize(
                    tx.get('name', ''),
                    tx.get('merchant_name')
                )

                # Determine income/expense
                amount = float(tx.get('amount', 0))
                # Plaid: positive = money leaving account (expense)
                # We flip for our convention: positive = income
                is_income = 1 if amount < 0 else 0
                is_expense = 1 if amount > 0 else 0

                try:
                    conn.execute("""
                        INSERT INTO core_transactions (
                            id, organization_id, plaid_transaction_id, plaid_item_id,
                            account_id, amount, date, name, merchant_name, merchant_normalized,
                            category, category_id, pending, payment_channel,
                            iso_currency_code, transaction_type, is_income, is_expense
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(plaid_transaction_id) DO UPDATE SET
                            amount = excluded.amount,
                            date = excluded.date,
                            name = excluded.name,
                            merchant_name = excluded.merchant_name,
                            merchant_normalized = excluded.merchant_normalized,
                            category = excluded.category,
                            pending = excluded.pending,
                            updated_at = datetime('now')
                    """, (
                        str(uuid4()),
                        organization_id,
                        tx.get('transaction_id'),
                        tx.get('plaid_item_id'),
                        tx.get('account_id'),
                        amount,
                        tx.get('date'),
                        tx.get('name', ''),
                        tx.get('merchant_name'),
                        merchant_normalized,
                        json.dumps(tx.get('category')) if tx.get('category') else None,
                        tx.get('category_id'),
                        1 if tx.get('pending') else 0,
                        tx.get('payment_channel'),
                        tx.get('iso_currency_code', 'USD'),
                        tx.get('transaction_type'),
                        is_income,
                        is_expense,
                    ))
                    persisted += 1
                except Exception as e:
                    logger.warning(f"Failed to persist transaction {tx.get('transaction_id')}: {e}")

            conn.commit()

        return persisted

    def _derive_vendor_suggestions(self, organization_id: str) -> List[Dict[str, Any]]:
        """Get vendor suggestions from CORE transactions."""
        with self._get_conn() as conn:
            # Get existing vendors
            vendors = conn.execute(
                "SELECT vendor_id, name FROM vendors WHERE organization_id = ?",
                (organization_id,)
            ).fetchall()
            existing_vendors = [dict(v) for v in vendors]

            # Get expense transactions
            transactions = conn.execute("""
                SELECT * FROM core_transactions
                WHERE organization_id = ? AND is_expense = 1
                ORDER BY date DESC LIMIT 1000
            """, (organization_id,)).fetchall()

            tx_list = [dict(tx) for tx in transactions]

        return self.deriver.derive_vendor_suggestions(tx_list, existing_vendors)

    def _derive_customer_suggestions(self, organization_id: str) -> List[Dict[str, Any]]:
        """Get customer suggestions from CORE transactions."""
        with self._get_conn() as conn:
            # Get existing customers
            customers = conn.execute(
                "SELECT customer_id, name FROM customers WHERE organization_id = ?",
                (organization_id,)
            ).fetchall()
            existing_customers = [dict(c) for c in customers]

            # Get income transactions
            transactions = conn.execute("""
                SELECT * FROM core_transactions
                WHERE organization_id = ? AND is_income = 1
                ORDER BY date DESC LIMIT 1000
            """, (organization_id,)).fetchall()

            tx_list = [dict(tx) for tx in transactions]

        return self.deriver.derive_customer_suggestions(tx_list, existing_customers)

    def _mark_sync_running(
        self,
        organization_id: str,
        request_id: str,
    ) -> None:
        """
        Mark sync as running IMMEDIATELY when sync begins.

        Sets:
        - sync_status = 'running'
        - sync_started_at = now()
        - last_sync_request_id = request_id

        This MUST be called at the very start of sync_organization().
        """
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO core_sync_metadata (
                    id, organization_id, sync_status, sync_started_at, last_sync_request_id
                ) VALUES (?, ?, 'running', datetime('now'), ?)
                ON CONFLICT(organization_id) DO UPDATE SET
                    sync_status = 'running',
                    sync_started_at = datetime('now'),
                    last_sync_request_id = excluded.last_sync_request_id,
                    updated_at = datetime('now')
            """, (
                str(uuid4()),
                organization_id,
                request_id,
            ))
            conn.commit()

    def _update_sync_status(
        self,
        organization_id: str,
        status: str,
        request_id: str,
        transactions_synced: Optional[int] = None,
        entities_derived: Optional[int] = None,
        error_message: Optional[str] = None,
        is_full_success: bool = False,
    ) -> None:
        """
        Update CORE sync metadata on completion (success or failure).

        CRITICAL:
        - last_successful_sync_at is ONLY set when is_full_success=True
        - sync_started_at is cleared (set to NULL) on completion
        - Partial successes or failures do NOT update last_successful_sync_at
        """
        with self._get_conn() as conn:
            # Build the SQL based on whether this is a full success
            if is_full_success:
                # Full success - update last_successful_sync_at, clear error, reset retry count
                # Clear sync_started_at since sync is complete
                conn.execute("""
                    INSERT INTO core_sync_metadata (
                        id, organization_id, last_synced_at, last_successful_sync_at,
                        last_sync_request_id, transactions_synced, entities_derived,
                        sync_status, error_message, retry_count, sync_started_at
                    ) VALUES (?, ?, datetime('now'), datetime('now'), ?, ?, ?, ?, NULL, 0, NULL)
                    ON CONFLICT(organization_id) DO UPDATE SET
                        last_synced_at = datetime('now'),
                        last_successful_sync_at = datetime('now'),
                        last_sync_request_id = excluded.last_sync_request_id,
                        transactions_synced = excluded.transactions_synced,
                        entities_derived = excluded.entities_derived,
                        sync_status = excluded.sync_status,
                        error_message = NULL,
                        retry_count = 0,
                        sync_started_at = NULL,
                        updated_at = datetime('now')
                """, (
                    str(uuid4()),
                    organization_id,
                    request_id,
                    transactions_synced,
                    entities_derived,
                    status,
                ))
            else:
                # Not a full success - do NOT update last_successful_sync_at
                # Clear sync_started_at since sync is complete (even if failed)
                conn.execute("""
                    INSERT INTO core_sync_metadata (
                        id, organization_id, last_synced_at, last_sync_request_id,
                        transactions_synced, entities_derived, sync_status, error_message, sync_started_at
                    ) VALUES (?, ?, datetime('now'), ?, ?, ?, ?, ?, NULL)
                    ON CONFLICT(organization_id) DO UPDATE SET
                        last_synced_at = datetime('now'),
                        last_sync_request_id = excluded.last_sync_request_id,
                        transactions_synced = COALESCE(excluded.transactions_synced, transactions_synced),
                        entities_derived = COALESCE(excluded.entities_derived, entities_derived),
                        sync_status = excluded.sync_status,
                        error_message = excluded.error_message,
                        sync_started_at = NULL,
                        updated_at = datetime('now')
                """, (
                    str(uuid4()),
                    organization_id,
                    request_id,
                    transactions_synced,
                    entities_derived,
                    status,
                    error_message,
                ))
            conn.commit()

    # =========================================================================
    # STATE RETRIEVAL
    # =========================================================================

    def get_core_state(self, organization_id: str) -> CoreState:
        """
        Get the complete CORE state for an organization.

        This is the SINGLE SOURCE OF TRUTH for dashboard data.

        CRITICAL: Unknown values = null, NEVER 0.
        """
        with self._get_conn() as conn:
            # Get sync metadata
            sync_row = conn.execute("""
                SELECT * FROM core_sync_metadata WHERE organization_id = ?
            """, (organization_id,)).fetchone()

            if sync_row:
                sync_metadata = CoreSyncMetadata(
                    organization_id=organization_id,
                    sync_started_at=datetime.fromisoformat(sync_row['sync_started_at']) if sync_row['sync_started_at'] else None,
                    last_synced_at=datetime.fromisoformat(sync_row['last_synced_at']) if sync_row['last_synced_at'] else None,
                    last_successful_sync_at=datetime.fromisoformat(sync_row['last_successful_sync_at']) if sync_row['last_successful_sync_at'] else None,
                    last_sync_request_id=sync_row['last_sync_request_id'],
                    transactions_synced=sync_row['transactions_synced'],
                    entities_derived=sync_row['entities_derived'],
                    sync_status=sync_row['sync_status'],
                    error_message=sync_row['error_message'],
                    last_retry_at=datetime.fromisoformat(sync_row['last_retry_at']) if sync_row['last_retry_at'] else None,
                    retry_count=sync_row['retry_count'] or 0,
                )
            else:
                sync_metadata = CoreSyncMetadata(
                    organization_id=organization_id,
                    sync_started_at=None,
                    last_synced_at=None,
                    last_successful_sync_at=None,
                    last_sync_request_id=None,
                    transactions_synced=None,
                    entities_derived=None,
                    sync_status='never',
                    error_message=None,
                    last_retry_at=None,
                    retry_count=0,
                )

            # Get Plaid items
            plaid_items = conn.execute("""
                SELECT id, item_id, institution_id, institution_name, status,
                       last_synced_at, error_code, error_message, created_at
                FROM plaid_items WHERE organization_id = ?
            """, (organization_id,)).fetchall()
            plaid_items_list = [dict(row) for row in plaid_items]

            # Compute metrics from CORE data
            metrics = self._compute_metrics(conn, organization_id)

            # Get recent transactions
            recent_tx = conn.execute("""
                SELECT * FROM core_transactions
                WHERE organization_id = ?
                ORDER BY date DESC LIMIT 20
            """, (organization_id,)).fetchall()
            recent_transactions = [dict(row) for row in recent_tx]

            # Get entity summaries
            customer_summary = self._get_customer_summary(conn, organization_id)
            vendor_summary = self._get_vendor_summary(conn, organization_id)
            invoice_summary = self._get_invoice_summary(conn, organization_id)
            bill_summary = self._get_bill_summary(conn, organization_id)

        return CoreState(
            organization_id=organization_id,
            sync_metadata=sync_metadata,
            metrics=metrics,
            plaid_items=plaid_items_list,
            recent_transactions=recent_transactions,
            customer_summary=customer_summary,
            vendor_summary=vendor_summary,
            invoice_summary=invoice_summary,
            bill_summary=bill_summary,
        )

    def _compute_metrics(self, conn: sqlite3.Connection, organization_id: str) -> CoreMetrics:
        """
        Compute derived metrics from CORE entities.

        CRITICAL: Unknown = null, NEVER 0.
        """
        # Transaction metrics
        tx_stats = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN is_income = 1 THEN ABS(amount) ELSE 0 END) as income,
                SUM(CASE WHEN is_expense = 1 THEN amount ELSE 0 END) as expenses
            FROM core_transactions WHERE organization_id = ?
        """, (organization_id,)).fetchone()

        total_transactions = tx_stats['total'] if tx_stats['total'] > 0 else None
        total_income = tx_stats['income'] if tx_stats['income'] else None
        total_expenses = tx_stats['expenses'] if tx_stats['expenses'] else None

        # Net cashflow (only if we have data)
        net_cashflow = None
        if total_income is not None or total_expenses is not None:
            net_cashflow = (total_income or 0) - (total_expenses or 0)

        # Entity counts
        customer_count = conn.execute(
            "SELECT COUNT(*) FROM customers WHERE organization_id = ?",
            (organization_id,)
        ).fetchone()[0]
        customer_count = customer_count if customer_count > 0 else None

        vendor_count = conn.execute(
            "SELECT COUNT(*) FROM vendors WHERE organization_id = ?",
            (organization_id,)
        ).fetchone()[0]
        vendor_count = vendor_count if vendor_count > 0 else None

        invoice_count = conn.execute(
            "SELECT COUNT(*) FROM invoices WHERE organization_id = ?",
            (organization_id,)
        ).fetchone()[0]
        invoice_count = invoice_count if invoice_count > 0 else None

        bill_count = conn.execute(
            "SELECT COUNT(*) FROM bills WHERE organization_id = ?",
            (organization_id,)
        ).fetchone()[0]
        bill_count = bill_count if bill_count > 0 else None

        # AR/AP outstanding
        ar_row = conn.execute("""
            SELECT SUM(CAST(balance_due AS REAL)) as outstanding
            FROM invoices WHERE organization_id = ? AND status NOT IN ('paid', 'void')
        """, (organization_id,)).fetchone()
        ar_outstanding = ar_row['outstanding'] if ar_row and ar_row['outstanding'] else None

        ap_row = conn.execute("""
            SELECT SUM(CAST(balance_due AS REAL)) as outstanding
            FROM bills WHERE organization_id = ? AND status NOT IN ('paid', 'void')
        """, (organization_id,)).fetchone()
        ap_outstanding = ap_row['outstanding'] if ap_row and ap_row['outstanding'] else None

        # Plaid items
        plaid_row = conn.execute("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) as active
            FROM plaid_items WHERE organization_id = ?
        """, (organization_id,)).fetchone()
        plaid_item_count = plaid_row['total'] if plaid_row['total'] > 0 else None
        active_account_count = plaid_row['active'] if plaid_row['active'] and plaid_row['active'] > 0 else None

        return CoreMetrics(
            total_transactions=total_transactions,
            total_income=total_income,
            total_expenses=total_expenses,
            net_cashflow=net_cashflow,
            customer_count=customer_count,
            vendor_count=vendor_count,
            invoice_count=invoice_count,
            bill_count=bill_count,
            ar_outstanding=ar_outstanding,
            ap_outstanding=ap_outstanding,
            plaid_item_count=plaid_item_count,
            active_account_count=active_account_count,
        )

    def _get_customer_summary(self, conn: sqlite3.Connection, organization_id: str) -> Optional[Dict[str, Any]]:
        """Get customer summary (null if no customers)."""
        row = conn.execute("""
            SELECT COUNT(*) as count,
                   SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) as active
            FROM customers WHERE organization_id = ?
        """, (organization_id,)).fetchone()

        if not row or row['count'] == 0:
            return None

        return {
            'total_count': row['count'],
            'active_count': row['active'] or 0,
        }

    def _get_vendor_summary(self, conn: sqlite3.Connection, organization_id: str) -> Optional[Dict[str, Any]]:
        """Get vendor summary (null if no vendors)."""
        row = conn.execute("""
            SELECT COUNT(*) as count,
                   SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) as active
            FROM vendors WHERE organization_id = ?
        """, (organization_id,)).fetchone()

        if not row or row['count'] == 0:
            return None

        return {
            'total_count': row['count'],
            'active_count': row['active'] or 0,
        }

    def _get_invoice_summary(self, conn: sqlite3.Connection, organization_id: str) -> Optional[Dict[str, Any]]:
        """Get invoice summary (null if no invoices)."""
        row = conn.execute("""
            SELECT COUNT(*) as count,
                   SUM(CASE WHEN status = 'draft' THEN 1 ELSE 0 END) as draft,
                   SUM(CASE WHEN status = 'sent' THEN 1 ELSE 0 END) as sent,
                   SUM(CASE WHEN status = 'paid' THEN 1 ELSE 0 END) as paid,
                   SUM(CASE WHEN status = 'overdue' THEN 1 ELSE 0 END) as overdue
            FROM invoices WHERE organization_id = ?
        """, (organization_id,)).fetchone()

        if not row or row['count'] == 0:
            return None

        return {
            'total_count': row['count'],
            'draft_count': row['draft'] or 0,
            'sent_count': row['sent'] or 0,
            'paid_count': row['paid'] or 0,
            'overdue_count': row['overdue'] or 0,
        }

    def _get_bill_summary(self, conn: sqlite3.Connection, organization_id: str) -> Optional[Dict[str, Any]]:
        """Get bill summary (null if no bills)."""
        row = conn.execute("""
            SELECT COUNT(*) as count,
                   SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                   SUM(CASE WHEN status = 'paid' THEN 1 ELSE 0 END) as paid,
                   SUM(CASE WHEN status = 'overdue' THEN 1 ELSE 0 END) as overdue
            FROM bills WHERE organization_id = ?
        """, (organization_id,)).fetchone()

        if not row or row['count'] == 0:
            return None

        return {
            'total_count': row['count'],
            'pending_count': row['pending'] or 0,
            'paid_count': row['paid'] or 0,
            'overdue_count': row['overdue'] or 0,
        }


# =============================================================================
# SINGLETON
# =============================================================================


_core_sync_service: Optional[CoreSyncService] = None


def get_core_sync_service() -> CoreSyncService:
    """Get or create the global CoreSyncService instance."""
    global _core_sync_service
    if _core_sync_service is None:
        _core_sync_service = CoreSyncService()
    return _core_sync_service
