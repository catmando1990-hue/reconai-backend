"""
CANONICAL CORE STATE FACTORY

Single source of truth for CoreState mock data in tests.
EVERY test MUST use this factory - no inline mocks allowed.

CONTRACT VERSION: 1
Schema mirrors: app/routers/core_state.py (CoreStateResponse)

RULES:
- Factory produces valid CoreStateResponse by default
- Use builder methods for test-specific variations
- Schema changes MUST update this file FIRST
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import uuid4

from app.routers.core_state import (
    SYNC_CONTRACT_VERSION,
    VALID_SYNC_STATUSES,
    SyncLifecycleResponse,
    CoreSyncMetadataResponse,
    CoreMetricsResponse,
    StalenessInfo,
    RecentEvidenceResponse,
    CoreStateResponse,
    SyncStatusValidationError,
)


# =============================================================================
# SCHEMA ASSERTION HELPER
# =============================================================================


class SchemaValidationError(Exception):
    """Raised when a CoreState object violates the canonical schema."""
    pass


def assert_valid_core_state(state: Dict[str, Any], context: str = "") -> None:
    """
    Assert a CoreState dict matches the canonical schema.
    FAIL-CLOSED: Raises immediately on any violation.

    Args:
        state: The state dict to validate
        context: Optional context for error messages

    Raises:
        SchemaValidationError: If schema is violated
    """
    prefix = f"[{context}] " if context else ""

    if not isinstance(state, dict):
        raise SchemaValidationError(
            f"{prefix}CoreState must be a dict, got {type(state).__name__}"
        )

    # Required top-level fields
    required_fields = {
        "success",
        "request_id",
        "organization_id",
        "available",
        "sync",
        "staleness",
        "sync_metadata",
        "metrics",
        "evidence",
        "plaid_items",
        "recent_transactions",
    }

    # Optional top-level fields
    optional_fields = {
        "customer_summary",
        "vendor_summary",
        "invoice_summary",
        "bill_summary",
    }

    allowed_fields = required_fields | optional_fields

    # Check for missing required fields
    for field_name in required_fields:
        if field_name not in state:
            raise SchemaValidationError(
                f"{prefix}Missing required field: {field_name}"
            )

    # Check for extra fields
    for key in state.keys():
        if key not in allowed_fields:
            raise SchemaValidationError(
                f"{prefix}Unexpected field: {key}"
            )

    # Type validations for top-level fields
    if not isinstance(state["success"], bool):
        raise SchemaValidationError(
            f"{prefix}success must be bool, got {type(state['success']).__name__}"
        )
    if not isinstance(state["request_id"], str):
        raise SchemaValidationError(
            f"{prefix}request_id must be str, got {type(state['request_id']).__name__}"
        )
    if not isinstance(state["organization_id"], str):
        raise SchemaValidationError(
            f"{prefix}organization_id must be str, got {type(state['organization_id']).__name__}"
        )
    if not isinstance(state["available"], bool):
        raise SchemaValidationError(
            f"{prefix}available must be bool, got {type(state['available']).__name__}"
        )
    if not isinstance(state["plaid_items"], list):
        raise SchemaValidationError(
            f"{prefix}plaid_items must be list, got {type(state['plaid_items']).__name__}"
        )
    if not isinstance(state["recent_transactions"], list):
        raise SchemaValidationError(
            f"{prefix}recent_transactions must be list, got {type(state['recent_transactions']).__name__}"
        )

    # Validate nested objects
    _assert_valid_sync(state["sync"], f"{prefix}sync")
    _assert_valid_staleness(state["staleness"], f"{prefix}staleness")
    _assert_valid_sync_metadata(state["sync_metadata"], f"{prefix}sync_metadata")
    _assert_valid_metrics(state["metrics"], f"{prefix}metrics")
    _assert_valid_evidence(state["evidence"], f"{prefix}evidence")


def _assert_valid_sync(sync: Dict[str, Any], context: str) -> None:
    """Validate sync lifecycle object."""
    if not isinstance(sync, dict):
        raise SchemaValidationError(
            f"{context} must be dict, got {type(sync).__name__}"
        )

    required_fields = {
        "sync_version",
        "status",
        "sync_started_at",
        "last_completed_at",
        "last_successful_at",
        "error_reason",
        "request_id",
    }

    # Check for missing required fields
    for field_name in required_fields:
        if field_name not in sync:
            raise SchemaValidationError(
                f"{context}: Missing required field: {field_name}"
            )

    # Check for extra fields
    for key in sync.keys():
        if key not in required_fields:
            raise SchemaValidationError(
                f"{context}: Unexpected field: {key}"
            )

    # Validate sync_version
    if not isinstance(sync["sync_version"], int):
        raise SchemaValidationError(
            f"{context}.sync_version must be int, got {type(sync['sync_version']).__name__}"
        )

    # Validate status enum
    if not isinstance(sync["status"], str):
        raise SchemaValidationError(
            f"{context}.status must be str, got {type(sync['status']).__name__}"
        )
    if sync["status"] not in VALID_SYNC_STATUSES:
        raise SchemaValidationError(
            f"{context}.status must be one of {sorted(VALID_SYNC_STATUSES)}, got '{sync['status']}'"
        )

    # Optional fields can be str or None
    for opt_field in ["sync_started_at", "last_completed_at", "last_successful_at", "error_reason", "request_id"]:
        val = sync[opt_field]
        if val is not None and not isinstance(val, str):
            raise SchemaValidationError(
                f"{context}.{opt_field} must be str or None, got {type(val).__name__}"
            )


def _assert_valid_staleness(staleness: Dict[str, Any], context: str) -> None:
    """Validate staleness info object."""
    if not isinstance(staleness, dict):
        raise SchemaValidationError(
            f"{context} must be dict, got {type(staleness).__name__}"
        )

    required_fields = {"stale", "stale_reason", "auto_retry_scheduled"}

    for field_name in required_fields:
        if field_name not in staleness:
            raise SchemaValidationError(
                f"{context}: Missing required field: {field_name}"
            )

    for key in staleness.keys():
        if key not in required_fields:
            raise SchemaValidationError(
                f"{context}: Unexpected field: {key}"
            )

    if not isinstance(staleness["stale"], bool):
        raise SchemaValidationError(
            f"{context}.stale must be bool"
        )
    if staleness["stale_reason"] is not None and not isinstance(staleness["stale_reason"], str):
        raise SchemaValidationError(
            f"{context}.stale_reason must be str or None"
        )
    if not isinstance(staleness["auto_retry_scheduled"], bool):
        raise SchemaValidationError(
            f"{context}.auto_retry_scheduled must be bool"
        )


def _assert_valid_sync_metadata(metadata: Dict[str, Any], context: str) -> None:
    """Validate sync metadata object."""
    if not isinstance(metadata, dict):
        raise SchemaValidationError(
            f"{context} must be dict, got {type(metadata).__name__}"
        )

    required_fields = {
        "organization_id",
        "last_synced_at",
        "last_successful_sync_at",
        "last_sync_request_id",
        "transactions_synced",
        "entities_derived",
        "sync_status",
        "sync_started_at",
        "error_message",
    }

    for field_name in required_fields:
        if field_name not in metadata:
            raise SchemaValidationError(
                f"{context}: Missing required field: {field_name}"
            )

    for key in metadata.keys():
        if key not in required_fields:
            raise SchemaValidationError(
                f"{context}: Unexpected field: {key}"
            )


def _assert_valid_metrics(metrics: Dict[str, Any], context: str) -> None:
    """Validate metrics object."""
    if not isinstance(metrics, dict):
        raise SchemaValidationError(
            f"{context} must be dict, got {type(metrics).__name__}"
        )

    required_fields = {
        "total_transactions",
        "total_income",
        "total_expenses",
        "net_cashflow",
        "customer_count",
        "vendor_count",
        "invoice_count",
        "bill_count",
        "ar_outstanding",
        "ap_outstanding",
        "plaid_item_count",
        "active_account_count",
    }

    for field_name in required_fields:
        if field_name not in metrics:
            raise SchemaValidationError(
                f"{context}: Missing required field: {field_name}"
            )

    for key in metrics.keys():
        if key not in required_fields:
            raise SchemaValidationError(
                f"{context}: Unexpected field: {key}"
            )


def _assert_valid_evidence(evidence: Dict[str, Any], context: str) -> None:
    """Validate evidence object."""
    if not isinstance(evidence, dict):
        raise SchemaValidationError(
            f"{context} must be dict, got {type(evidence).__name__}"
        )

    required_fields = {"recent_transactions", "recent_entity_changes"}

    for field_name in required_fields:
        if field_name not in evidence:
            raise SchemaValidationError(
                f"{context}: Missing required field: {field_name}"
            )

    for key in evidence.keys():
        if key not in required_fields:
            raise SchemaValidationError(
                f"{context}: Unexpected field: {key}"
            )

    if not isinstance(evidence["recent_transactions"], list):
        raise SchemaValidationError(
            f"{context}.recent_transactions must be list"
        )
    if not isinstance(evidence["recent_entity_changes"], list):
        raise SchemaValidationError(
            f"{context}.recent_entity_changes must be list"
        )


# =============================================================================
# CORE STATE FACTORY
# =============================================================================


def _generate_request_id() -> str:
    """Generate a test request ID."""
    return f"test_{uuid4().hex[:16]}"


def _iso_now() -> str:
    """Generate current ISO timestamp."""
    return datetime.utcnow().isoformat()


def core_state_factory(
    *,
    success: bool = True,
    request_id: Optional[str] = None,
    organization_id: str = "org_test123",
    available: bool = False,
    sync_status: str = "never",
    sync_started_at: Optional[str] = None,
    last_completed_at: Optional[str] = None,
    last_successful_at: Optional[str] = None,
    error_reason: Optional[str] = None,
    stale: bool = True,
    stale_reason: Optional[str] = "CORE has never been synced",
    auto_retry_scheduled: bool = False,
    total_transactions: Optional[int] = None,
    total_income: Optional[float] = None,
    total_expenses: Optional[float] = None,
    plaid_items: Optional[List[Dict[str, Any]]] = None,
    recent_transactions: Optional[List[Dict[str, Any]]] = None,
    customer_summary: Optional[Dict[str, Any]] = None,
    vendor_summary: Optional[Dict[str, Any]] = None,
    invoice_summary: Optional[Dict[str, Any]] = None,
    bill_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Create a valid CoreStateResponse dict with sensible defaults.
    Override specific fields as needed for test scenarios.

    All sync status values are validated against VALID_SYNC_STATUSES.

    Args:
        success: Whether the request succeeded
        request_id: Unique request identifier (auto-generated if not provided)
        organization_id: Organization ID
        available: Whether any data is available
        sync_status: One of "never", "running", "success", "failed"
        sync_started_at: ISO datetime when sync began
        last_completed_at: ISO datetime of last completion
        last_successful_at: ISO datetime of last successful sync
        error_reason: Error message if sync_status is "failed"
        stale: Whether data is stale
        stale_reason: Reason for staleness
        auto_retry_scheduled: Whether auto-retry was scheduled
        total_transactions: Total transaction count
        total_income: Total income amount
        total_expenses: Total expenses amount
        plaid_items: List of Plaid items
        recent_transactions: List of recent transactions
        customer_summary: Customer summary data
        vendor_summary: Vendor summary data
        invoice_summary: Invoice summary data
        bill_summary: Bill summary data

    Returns:
        Valid CoreStateResponse as a dict

    Raises:
        SyncStatusValidationError: If sync_status is invalid
    """
    # Validate sync status
    if sync_status not in VALID_SYNC_STATUSES:
        raise SyncStatusValidationError(
            f"Invalid sync status '{sync_status}'. Must be one of: {sorted(VALID_SYNC_STATUSES)}"
        )

    result = {
        "success": success,
        "request_id": request_id or _generate_request_id(),
        "organization_id": organization_id,
        "available": available,
        "sync": {
            "sync_version": SYNC_CONTRACT_VERSION,
            "status": sync_status,
            "sync_started_at": sync_started_at,
            "last_completed_at": last_completed_at,
            "last_successful_at": last_successful_at,
            "error_reason": error_reason,
            "request_id": None,
        },
        "staleness": {
            "stale": stale,
            "stale_reason": stale_reason,
            "auto_retry_scheduled": auto_retry_scheduled,
        },
        "sync_metadata": {
            "organization_id": organization_id,
            "last_synced_at": last_completed_at,
            "last_successful_sync_at": last_successful_at,
            "last_sync_request_id": None,
            "transactions_synced": total_transactions,
            "entities_derived": None,
            "sync_status": sync_status,
            "sync_started_at": sync_started_at,
            "error_message": error_reason,
        },
        "metrics": {
            "total_transactions": total_transactions,
            "total_income": total_income,
            "total_expenses": total_expenses,
            "net_cashflow": (total_income or 0) - (total_expenses or 0) if total_income or total_expenses else None,
            "customer_count": None,
            "vendor_count": None,
            "invoice_count": None,
            "bill_count": None,
            "ar_outstanding": None,
            "ap_outstanding": None,
            "plaid_item_count": len(plaid_items) if plaid_items else None,
            "active_account_count": None,
        },
        "evidence": {
            "recent_transactions": (recent_transactions or [])[:3],
            "recent_entity_changes": [],
        },
        "plaid_items": plaid_items or [],
        "recent_transactions": recent_transactions or [],
        "customer_summary": customer_summary,
        "vendor_summary": vendor_summary,
        "invoice_summary": invoice_summary,
        "bill_summary": bill_summary,
    }

    # Validate the result
    assert_valid_core_state(result, "core_state_factory")

    return result


# =============================================================================
# PRESET FACTORIES - Common test scenarios
# =============================================================================


def empty_org_state() -> Dict[str, Any]:
    """
    Empty organization - no data available.
    Use for testing "No Financial Data Yet" state.
    """
    return core_state_factory(
        available=False,
        sync_status="never",
        stale=True,
        stale_reason="CORE has never been synced",
    )


def partial_org_state() -> Dict[str, Any]:
    """
    Partial organization - some data available.
    Use for testing mixed data display.
    """
    now = _iso_now()
    return core_state_factory(
        available=True,
        sync_status="success",
        last_completed_at=now,
        last_successful_at=now,
        stale=False,
        stale_reason=None,
        total_transactions=50,
        total_income=10000.0,
        total_expenses=5000.0,
        plaid_items=[
            {"item_id": "item_1", "status": "healthy", "institution_name": "Chase"},
        ],
        recent_transactions=[
            {"id": "tx1", "date": "2024-01-15", "amount": -500, "merchant_name": "Office Supplies"},
            {"id": "tx2", "date": "2024-01-14", "amount": 1200, "merchant_name": "Client Payment"},
        ],
    )


def full_org_state() -> Dict[str, Any]:
    """
    Full organization - all data available.
    Use for testing complete data display.
    """
    now = _iso_now()
    return core_state_factory(
        available=True,
        sync_status="success",
        last_completed_at=now,
        last_successful_at=now,
        stale=False,
        stale_reason=None,
        total_transactions=500,
        total_income=150000.0,
        total_expenses=80000.0,
        plaid_items=[
            {"item_id": "item_1", "status": "healthy", "institution_name": "Chase"},
            {"item_id": "item_2", "status": "healthy", "institution_name": "Bank of America"},
        ],
        recent_transactions=[
            {"id": "tx1", "date": "2024-01-15", "amount": -500, "merchant_name": "Office Supplies"},
            {"id": "tx2", "date": "2024-01-14", "amount": 1200, "merchant_name": "Client Payment"},
            {"id": "tx3", "date": "2024-01-13", "amount": -300, "merchant_name": "Utilities"},
        ],
        customer_summary={"total_count": 12, "active_count": 10},
        vendor_summary={"total_count": 8, "active_count": 6},
        invoice_summary={"total_count": 25, "draft_count": 2, "sent_count": 3, "paid_count": 20, "overdue_count": 0},
        bill_summary={"total_count": 18, "pending_count": 2, "paid_count": 15, "overdue_count": 1},
    )


# =============================================================================
# SYNC STATE BUILDERS - For testing sync lifecycle
# =============================================================================


def with_sync_running(base: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Create state with sync running."""
    now = _iso_now()
    b = base or partial_org_state()
    return core_state_factory(
        available=b["available"],
        sync_status="running",
        sync_started_at=now,
        stale=False,
        stale_reason=None,
        total_transactions=b["metrics"]["total_transactions"],
        plaid_items=b["plaid_items"],
        recent_transactions=b["recent_transactions"],
    )


def with_sync_failed(error_reason: str, base: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Create state with sync failed."""
    started = (datetime.utcnow() - timedelta(minutes=5)).isoformat()
    b = base or partial_org_state()
    return core_state_factory(
        available=b["available"],
        sync_status="failed",
        sync_started_at=started,
        error_reason=error_reason,
        stale=True,
        stale_reason="Previous sync failed",
        total_transactions=b["metrics"]["total_transactions"],
        plaid_items=b["plaid_items"],
        recent_transactions=b["recent_transactions"],
    )


def with_stale_data(hours_ago: int = 48, base: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Create state with stale data (last sync > threshold hours ago)."""
    last_sync = (datetime.utcnow() - timedelta(hours=hours_ago)).isoformat()
    b = base or partial_org_state()
    return core_state_factory(
        available=b["available"],
        sync_status="success",
        last_completed_at=last_sync,
        last_successful_at=last_sync,
        stale=True,
        stale_reason=f"Last successful sync was {hours_ago}h ago (threshold: 24h)",
        total_transactions=b["metrics"]["total_transactions"],
        plaid_items=b["plaid_items"],
        recent_transactions=b["recent_transactions"],
    )
