# app/routers/core_state.py
"""
CORE State API - Single source of truth for organization state.

This endpoint returns the complete CORE state for an organization,
derived entirely from CORE entities. All dashboard metrics MUST
come from this endpoint.

CRITICAL RULES:
- Unknown values = null (NEVER 0)
- All metrics derived from CORE entities
- No independent database queries for metrics
- Staleness detection with auto-retry
- Auto-hydration via triggers (no frontend dependency)

STALENESS RULES:
- If last_successful_sync_at is null → stale=true (reason: "CORE has never been synced")
- If now - last_successful_sync_at > 24h → stale=true (reason: "Last successful sync > 24h ago")
- If sync_status == 'failed' → stale=true (reason: "Previous sync failed")
- Otherwise → stale=false

AUTO-RETRY:
- If stale=true AND no sync running AND cooldown passed → schedule background retry
- Never blocks the response
- Respects 1-hour cooldown
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.auth_context import AuthContext, get_current_context
from app.services.core_sync import (
    CoreSyncService,
    CoreState,
    STALE_THRESHOLD_HOURS,
    get_core_sync_service,
)
from app.services.core_sync_triggers import maybe_schedule_auto_retry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/core", tags=["core"])


# =============================================================================
# RESPONSE MODELS
# =============================================================================


class CoreSyncMetadataResponse(BaseModel):
    """Sync metadata response."""
    organization_id: str
    last_synced_at: Optional[str]
    last_successful_sync_at: Optional[str]
    last_sync_request_id: Optional[str]
    transactions_synced: Optional[int]
    entities_derived: Optional[int]
    sync_status: str  # 'never', 'success', 'failed', 'syncing'
    error_message: Optional[str]


class CoreMetricsResponse(BaseModel):
    """
    Derived metrics response.

    CRITICAL: null = unknown, NEVER 0.
    """
    # Transaction metrics
    total_transactions: Optional[int] = None
    total_income: Optional[float] = None
    total_expenses: Optional[float] = None
    net_cashflow: Optional[float] = None

    # Entity counts
    customer_count: Optional[int] = None
    vendor_count: Optional[int] = None
    invoice_count: Optional[int] = None
    bill_count: Optional[int] = None

    # AR/AP metrics
    ar_outstanding: Optional[float] = None
    ap_outstanding: Optional[float] = None

    # Connected accounts
    plaid_item_count: Optional[int] = None
    active_account_count: Optional[int] = None


class StalenessInfo(BaseModel):
    """
    Staleness information for CORE state.

    stale=true does NOT mean unavailable.
    available=true + stale=true is a valid state.
    """
    stale: bool
    stale_reason: Optional[str] = None
    auto_retry_scheduled: bool = False


class CoreStateResponse(BaseModel):
    """
    Complete CORE state response.

    This is the SINGLE SOURCE OF TRUTH for dashboard data.
    All frontend metrics MUST come from this structure.
    """
    success: bool
    request_id: str
    organization_id: str
    available: bool  # True if we have any data to show
    staleness: StalenessInfo
    sync_metadata: CoreSyncMetadataResponse
    metrics: CoreMetricsResponse
    plaid_items: list
    recent_transactions: list
    customer_summary: Optional[Dict[str, Any]] = None
    vendor_summary: Optional[Dict[str, Any]] = None
    invoice_summary: Optional[Dict[str, Any]] = None
    bill_summary: Optional[Dict[str, Any]] = None


class CoreSyncResponse(BaseModel):
    """Sync operation response."""
    success: bool
    request_id: str
    transactions_synced: Optional[int] = None
    plaid_items: Optional[int] = None
    active_items: Optional[int] = None
    vendor_suggestions: Optional[int] = None
    customer_suggestions: Optional[int] = None
    sync_errors: Optional[list] = None
    error: Optional[str] = None
    message: Optional[str] = None
    is_full_success: Optional[bool] = None


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def _get_client_ip(request: Request) -> Optional[str]:
    """Extract client IP from request headers."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def _get_user_agent(request: Request) -> Optional[str]:
    """Extract user agent from request headers."""
    return request.headers.get("User-Agent")


def _generate_request_id() -> str:
    """Generate request ID."""
    from uuid import uuid4
    return f"core_{uuid4().hex[:16]}"


def _compute_staleness(state: CoreState) -> tuple[bool, Optional[str]]:
    """
    Compute staleness status from CORE state.

    Returns:
        (is_stale, stale_reason)

    RULES:
    - If last_successful_sync_at is null → stale=true
    - If now - last_successful_sync_at > STALE_THRESHOLD → stale=true
    - If sync_status == 'failed' → stale=true
    - Otherwise → stale=false
    """
    metadata = state.sync_metadata

    # Rule 1: Never synced
    if metadata.last_successful_sync_at is None:
        return True, "CORE has never been synced"

    # Rule 2: Previous sync failed
    if metadata.sync_status == 'failed':
        return True, "Previous sync failed"

    # Rule 3: Stale by time threshold
    now = datetime.utcnow()
    age = now - metadata.last_successful_sync_at
    if age > timedelta(hours=STALE_THRESHOLD_HOURS):
        hours_ago = int(age.total_seconds() / 3600)
        return True, f"Last successful sync was {hours_ago}h ago (threshold: {STALE_THRESHOLD_HOURS}h)"

    # Not stale
    return False, None


def _compute_availability(state: CoreState) -> bool:
    """
    Determine if CORE data is available (has any data to show).

    Available = True if we have:
    - Any transactions OR
    - Any Plaid items OR
    - Any entities

    Available can be True even if stale.
    """
    # Check if we have any transactions
    if state.metrics.total_transactions is not None and state.metrics.total_transactions > 0:
        return True

    # Check if we have any Plaid items
    if state.plaid_items and len(state.plaid_items) > 0:
        return True

    # Check if we have any entities
    if state.metrics.customer_count is not None and state.metrics.customer_count > 0:
        return True
    if state.metrics.vendor_count is not None and state.metrics.vendor_count > 0:
        return True
    if state.metrics.invoice_count is not None and state.metrics.invoice_count > 0:
        return True
    if state.metrics.bill_count is not None and state.metrics.bill_count > 0:
        return True

    # No data available
    return False


# =============================================================================
# ENDPOINTS
# =============================================================================


@router.get("/state", response_model=CoreStateResponse)
async def get_core_state(
    ctx: AuthContext = Depends(get_current_context),
    core_service: CoreSyncService = Depends(get_core_sync_service),
) -> CoreStateResponse:
    """
    Get the complete CORE state for the organization.

    **Auth Required:** Yes (Bearer token)
    **Org Scoped:** Yes

    This is the SINGLE SOURCE OF TRUTH for dashboard data.
    All metrics are derived from CORE entities.

    CRITICAL:
    - Unknown values = null, NEVER 0
    - stale=true does NOT mean unavailable
    - Auto-retry is scheduled if stale (non-blocking)

    Returns:
        CoreStateResponse with complete organization state, staleness info
    """
    request_id = _generate_request_id()

    try:
        state = core_service.get_core_state(ctx["org_id"])

        # Compute staleness
        is_stale, stale_reason = _compute_staleness(state)

        # Compute availability
        is_available = _compute_availability(state)

        # Maybe schedule auto-retry if stale (non-blocking)
        auto_retry_scheduled = False
        if is_stale:
            auto_retry_scheduled = maybe_schedule_auto_retry(
                organization_id=ctx["org_id"],
                is_stale=is_stale,
                sync_status=state.sync_metadata.sync_status,
            )
            if auto_retry_scheduled:
                logger.info(f"Auto-retry scheduled for stale CORE: org={ctx['org_id']}")

        # Build staleness info
        staleness = StalenessInfo(
            stale=is_stale,
            stale_reason=stale_reason,
            auto_retry_scheduled=auto_retry_scheduled,
        )

        # Convert dataclasses to response models
        sync_metadata = CoreSyncMetadataResponse(
            organization_id=state.sync_metadata.organization_id,
            last_synced_at=state.sync_metadata.last_synced_at.isoformat() if state.sync_metadata.last_synced_at else None,
            last_successful_sync_at=state.sync_metadata.last_successful_sync_at.isoformat() if state.sync_metadata.last_successful_sync_at else None,
            last_sync_request_id=state.sync_metadata.last_sync_request_id,
            transactions_synced=state.sync_metadata.transactions_synced,
            entities_derived=state.sync_metadata.entities_derived,
            sync_status=state.sync_metadata.sync_status,
            error_message=state.sync_metadata.error_message,
        )

        metrics = CoreMetricsResponse(
            total_transactions=state.metrics.total_transactions,
            total_income=state.metrics.total_income,
            total_expenses=state.metrics.total_expenses,
            net_cashflow=state.metrics.net_cashflow,
            customer_count=state.metrics.customer_count,
            vendor_count=state.metrics.vendor_count,
            invoice_count=state.metrics.invoice_count,
            bill_count=state.metrics.bill_count,
            ar_outstanding=state.metrics.ar_outstanding,
            ap_outstanding=state.metrics.ap_outstanding,
            plaid_item_count=state.metrics.plaid_item_count,
            active_account_count=state.metrics.active_account_count,
        )

        return CoreStateResponse(
            success=True,
            request_id=request_id,
            organization_id=ctx["org_id"],
            available=is_available,
            staleness=staleness,
            sync_metadata=sync_metadata,
            metrics=metrics,
            plaid_items=state.plaid_items,
            recent_transactions=state.recent_transactions,
            customer_summary=state.customer_summary,
            vendor_summary=state.vendor_summary,
            invoice_summary=state.invoice_summary,
            bill_summary=state.bill_summary,
        )

    except Exception as e:
        logger.exception(f"Error getting CORE state: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "INTERNAL_ERROR",
                "error_code": "CORE_STATE_FAILED",
                "message": str(e),
                "request_id": request_id,
            },
        )


@router.post("/sync", response_model=CoreSyncResponse)
async def sync_organization(
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    core_service: CoreSyncService = Depends(get_core_sync_service),
) -> CoreSyncResponse:
    """
    Trigger a full CORE sync for the organization.

    **Auth Required:** Yes (Bearer token)
    **Org Scoped:** Yes

    ⚠️ DEPRECATED FOR NORMAL USE:
    Normal operation does NOT require calling this endpoint.
    CORE auto-hydrates via triggers when bank data changes.
    This endpoint is retained for:
    - Admin/debug use
    - Manual recovery scenarios
    - Initial setup testing

    Pipeline:
    1. Fetch transactions from all Plaid items
    2. Normalize merchants
    3. Persist transactions
    4. Derive entity suggestions
    5. Compute metrics
    6. Update sync metadata

    Returns:
        CoreSyncResponse with sync results
    """
    logger.info(
        f"Manual CORE sync triggered: org={ctx['org_id']} user={ctx['user_id']}"
    )

    result = core_service.sync_organization(
        organization_id=ctx["org_id"],
        user_id=ctx["user_id"],
        ip_address=_get_client_ip(request),
        user_agent=_get_user_agent(request),
    )

    return CoreSyncResponse(**result)


@router.get("/metrics", response_model=CoreMetricsResponse)
async def get_core_metrics(
    ctx: AuthContext = Depends(get_current_context),
    core_service: CoreSyncService = Depends(get_core_sync_service),
) -> CoreMetricsResponse:
    """
    Get derived metrics only.

    **Auth Required:** Yes (Bearer token)
    **Org Scoped:** Yes

    A lightweight endpoint that returns only the derived metrics,
    without the full state (transactions, items, etc.).

    CRITICAL: Unknown values = null, NEVER 0.

    Returns:
        CoreMetricsResponse with derived metrics
    """
    state = core_service.get_core_state(ctx["org_id"])

    return CoreMetricsResponse(
        total_transactions=state.metrics.total_transactions,
        total_income=state.metrics.total_income,
        total_expenses=state.metrics.total_expenses,
        net_cashflow=state.metrics.net_cashflow,
        customer_count=state.metrics.customer_count,
        vendor_count=state.metrics.vendor_count,
        invoice_count=state.metrics.invoice_count,
        bill_count=state.metrics.bill_count,
        ar_outstanding=state.metrics.ar_outstanding,
        ap_outstanding=state.metrics.ap_outstanding,
        plaid_item_count=state.metrics.plaid_item_count,
        active_account_count=state.metrics.active_account_count,
    )


@router.get("/sync-status")
async def get_sync_status(
    ctx: AuthContext = Depends(get_current_context),
    core_service: CoreSyncService = Depends(get_core_sync_service),
) -> Dict[str, Any]:
    """
    Get the current sync status with staleness info.

    **Auth Required:** Yes (Bearer token)
    **Org Scoped:** Yes

    A lightweight endpoint to check sync status without loading full state.

    Returns:
        Sync metadata with staleness info
    """
    state = core_service.get_core_state(ctx["org_id"])

    # Compute staleness
    is_stale, stale_reason = _compute_staleness(state)

    return {
        "success": True,
        "organization_id": ctx["org_id"],
        "sync_status": state.sync_metadata.sync_status,
        "last_synced_at": state.sync_metadata.last_synced_at.isoformat() if state.sync_metadata.last_synced_at else None,
        "last_successful_sync_at": state.sync_metadata.last_successful_sync_at.isoformat() if state.sync_metadata.last_successful_sync_at else None,
        "transactions_synced": state.sync_metadata.transactions_synced,
        "entities_derived": state.sync_metadata.entities_derived,
        "error_message": state.sync_metadata.error_message,
        "stale": is_stale,
        "stale_reason": stale_reason,
    }


@router.get("/vendor-suggestions")
async def get_vendor_suggestions(
    ctx: AuthContext = Depends(get_current_context),
    core_service: CoreSyncService = Depends(get_core_sync_service),
) -> Dict[str, Any]:
    """
    Get vendor suggestions derived from transactions.

    **Auth Required:** Yes (Bearer token)
    **Org Scoped:** Yes

    Returns suggested vendors based on expense transaction patterns.
    These are SUGGESTIONS only - not auto-created entities.

    Returns:
        List of vendor suggestions with transaction evidence
    """
    suggestions = core_service._derive_vendor_suggestions(ctx["org_id"])

    return {
        "success": True,
        "organization_id": ctx["org_id"],
        "suggestion_count": len(suggestions),
        "suggestions": suggestions,
    }


@router.get("/customer-suggestions")
async def get_customer_suggestions(
    ctx: AuthContext = Depends(get_current_context),
    core_service: CoreSyncService = Depends(get_core_sync_service),
) -> Dict[str, Any]:
    """
    Get customer suggestions derived from transactions.

    **Auth Required:** Yes (Bearer token)
    **Org Scoped:** Yes

    Returns suggested customers based on income transaction patterns.
    These are SUGGESTIONS only - not auto-created entities.

    Returns:
        List of customer suggestions with transaction evidence
    """
    suggestions = core_service._derive_customer_suggestions(ctx["org_id"])

    return {
        "success": True,
        "organization_id": ctx["org_id"],
        "suggestion_count": len(suggestions),
        "suggestions": suggestions,
    }
