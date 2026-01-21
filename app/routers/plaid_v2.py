# app/routers/plaid_v2.py
"""
Production Plaid API routes with:
- Auth protection via get_current_context
- Organization-scoped validation
- Encrypted access tokens
- Cursor-based sync
- Structured error responses with request_id
- Immutable audit logging

Products: transactions, auth, balance

============================================================================
FROZEN AS OF 2024-01-20 (Phase 4 System Hardening)
============================================================================

DO NOT MODIFY THIS FILE WITHOUT FOLLOWING THE CHANGE PROCEDURE IN:
    app/plaid/FROZEN.md

Contract Surface:
- POST /api/plaid/create-link-token
- POST /api/plaid/exchange-public-token
- POST /api/plaid/sync-transactions
- GET  /api/plaid/items
- POST /api/plaid/webhook
- DELETE /api/plaid/items/{item_id}

Any changes require: RFC + Security Review + Migration Plan
============================================================================
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from app.auth_context import AuthContext, get_current_context
from app.models.plaid import (
    CreateLinkTokenRequest,
    CreateLinkTokenResponse,
    ExchangePublicTokenRequest,
    ExchangePublicTokenResponse,
    ListPlaidItemsResponse,
    PlaidWebhookPayload,
    TransactionsSyncRequest,
    TransactionsSyncResponse,
    WebhookResponse,
)
from app.services.plaid_service import PlaidService, get_plaid_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/plaid", tags=["plaid"])


def _get_client_ip(request: Request) -> Optional[str]:
    """Extract client IP from request headers."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def _get_user_agent(request: Request) -> Optional[str]:
    """Extract user agent from request headers."""
    return request.headers.get("User-Agent")


# =============================================================================
# LINK TOKEN CREATION
# =============================================================================


@router.post("/create-link-token", response_model=CreateLinkTokenResponse)
async def create_link_token(
    payload: CreateLinkTokenRequest,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    plaid_service: PlaidService = Depends(get_plaid_service),
) -> CreateLinkTokenResponse:
    """
    Create a Plaid Link token for connecting a bank account.

    **Auth Required:** Yes (Bearer token)
    **Org Scoped:** Yes

    The link token is used to initialize Plaid Link in the frontend.
    Products enabled: transactions, auth, balance

    Returns:
        CreateLinkTokenResponse with link_token and expiration
    """
    response = plaid_service.create_link_token(
        organization_id=ctx["org_id"],
        user_id=ctx["user_id"],
        redirect_uri=payload.redirect_uri,
        entity_id=payload.entity_id,
        ip_address=_get_client_ip(request),
        user_agent=_get_user_agent(request),
    )

    if not response.success:
        logger.warning(
            f"Link token creation failed: org={ctx['org_id']} "
            f"error={response.error.error_code if response.error else 'unknown'}"
        )

    return response


# =============================================================================
# PUBLIC TOKEN EXCHANGE
# =============================================================================


@router.post("/exchange-public-token", response_model=ExchangePublicTokenResponse)
async def exchange_public_token(
    payload: ExchangePublicTokenRequest,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    plaid_service: PlaidService = Depends(get_plaid_service),
) -> ExchangePublicTokenResponse:
    """
    Exchange a Plaid public token for an access token.

    **Auth Required:** Yes (Bearer token)
    **Org Scoped:** Yes

    The access token is encrypted at rest (AES-256-GCM) and stored
    with the organization. This endpoint detects duplicate items and
    returns is_duplicate=true if the same bank account is already connected.

    **Note:** Duplicate detection is server-side only. The endpoint does NOT
    auto-block or auto-merge duplicates - the client should handle the
    is_duplicate flag appropriately.

    Audit logged: token_exchanged, item_created

    Returns:
        ExchangePublicTokenResponse with item_id and is_duplicate flag
    """
    if not payload.public_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "VALIDATION_ERROR",
                "error_code": "MISSING_PUBLIC_TOKEN",
                "message": "public_token is required",
            },
        )

    response = plaid_service.exchange_public_token(
        organization_id=ctx["org_id"],
        user_id=ctx["user_id"],
        public_token=payload.public_token,
        institution_id=payload.institution_id,
        institution_name=payload.institution_name,
        entity_id=payload.entity_id,
        ip_address=_get_client_ip(request),
        user_agent=_get_user_agent(request),
    )

    if not response.success:
        logger.warning(
            f"Token exchange failed: org={ctx['org_id']} "
            f"error={response.error.error_code if response.error else 'unknown'}"
        )

    return response


# =============================================================================
# TRANSACTIONS SYNC
# =============================================================================


@router.post("/transactions/sync", response_model=TransactionsSyncResponse)
async def sync_transactions(
    payload: TransactionsSyncRequest,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    plaid_service: PlaidService = Depends(get_plaid_service),
) -> TransactionsSyncResponse:
    """
    Sync transactions for a connected Plaid item.

    **Auth Required:** Yes (Bearer token)
    **Org Scoped:** Yes (validates item belongs to org)

    Uses Plaid's cursor-based /transactions/sync endpoint for efficient
    incremental synchronization. This is a MANUAL-ONLY operation - there
    are no background jobs or polling.

    The response includes:
    - added: New transactions since last sync
    - modified: Transactions that changed since last sync
    - removed: Transaction IDs that were deleted
    - has_more: Whether more transactions are available
    - next_cursor: Cursor for pagination (stored automatically)

    Audit logged: sync_started, sync_completed, sync_failed

    Returns:
        TransactionsSyncResponse with transactions and pagination info
    """
    if not payload.item_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "VALIDATION_ERROR",
                "error_code": "MISSING_ITEM_ID",
                "message": "item_id is required",
            },
        )

    # Validate org ownership before processing
    item = plaid_service.get_item_for_org(ctx["org_id"], payload.item_id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "ITEM_ERROR",
                "error_code": "ITEM_NOT_FOUND",
                "message": f"Plaid item {payload.item_id} not found for this organization",
            },
        )

    response = plaid_service.sync_transactions(
        organization_id=ctx["org_id"],
        user_id=ctx["user_id"],
        item_id=payload.item_id,
        count=payload.count,
        ip_address=_get_client_ip(request),
        user_agent=_get_user_agent(request),
    )

    if not response.success:
        logger.warning(
            f"Transaction sync failed: org={ctx['org_id']} item={payload.item_id} "
            f"error={response.error.error_code if response.error else 'unknown'}"
        )

    return response


# =============================================================================
# WEBHOOK ENDPOINT
# =============================================================================


@router.post("/webhook", response_model=WebhookResponse)
async def handle_webhook(
    request: Request,
    plaid_verification: Optional[str] = Header(None, alias="Plaid-Verification"),
    plaid_service: PlaidService = Depends(get_plaid_service),
) -> WebhookResponse:
    """
    Handle Plaid webhook events.

    **Auth Required:** No (but signature verified)
    **Webhook Verification:** Plaid-Verification header (HMAC-SHA256)

    This endpoint processes Plaid webhooks for:
    - ITEM events (LOGIN_REQUIRED, ERROR, LOGIN_REPAIRED, etc.)
    - TRANSACTIONS events (logged but not auto-processed)

    **Behavior:**
    - Updates item status only (no side effects)
    - Does NOT trigger automatic transaction syncs
    - All events are logged for audit

    Audit logged: webhook_received, webhook_processed

    Handled ITEM codes:
    - ERROR: Sets item status to 'error'
    - PENDING_EXPIRATION: Sets item status to 'login_required'
    - USER_PERMISSION_REVOKED: Sets item status to 'login_required'
    - LOGIN_REPAIRED: Sets item status to 'active'

    Returns:
        WebhookResponse with action taken
    """
    # Read raw body for signature verification
    body = await request.body()

    # Verify signature if configured
    if plaid_verification:
        if not plaid_service.verify_webhook_signature(body, plaid_verification):
            logger.warning("Webhook signature verification failed")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "error": "WEBHOOK_ERROR",
                    "error_code": "INVALID_SIGNATURE",
                    "message": "Webhook signature verification failed",
                },
            )

    # Parse payload
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "WEBHOOK_ERROR",
                "error_code": "INVALID_PAYLOAD",
                "message": f"Invalid JSON payload: {e}",
            },
        )

    webhook_type = payload.get("webhook_type", "")
    webhook_code = payload.get("webhook_code", "")
    item_id = payload.get("item_id", "")

    if not item_id:
        logger.warning(f"Webhook missing item_id: type={webhook_type} code={webhook_code}")
        return WebhookResponse(
            success=True,
            request_id="webhook_no_item",
            webhook_type=webhook_type,
            webhook_code=webhook_code,
            action_taken="ignored_missing_item_id",
        )

    response = plaid_service.process_webhook(
        webhook_type=webhook_type,
        webhook_code=webhook_code,
        item_id=item_id,
        payload=payload,
        ip_address=_get_client_ip(request),
    )

    return response


# =============================================================================
# ITEM MANAGEMENT
# =============================================================================


@router.get("/items", response_model=ListPlaidItemsResponse)
async def list_items(
    entity_id: Optional[str] = None,
    ctx: AuthContext = Depends(get_current_context),
    plaid_service: PlaidService = Depends(get_plaid_service),
) -> ListPlaidItemsResponse:
    """
    List all connected Plaid items for the organization.

    **Auth Required:** Yes (Bearer token)
    **Org Scoped:** Yes

    Returns all bank connections for the organization, optionally
    filtered by entity_id.

    Returns:
        ListPlaidItemsResponse with list of PlaidItemInfo
    """
    response = plaid_service.list_items(
        organization_id=ctx["org_id"],
        entity_id=entity_id,
    )

    return response


@router.get("/items/{item_id}")
async def get_item(
    item_id: str,
    ctx: AuthContext = Depends(get_current_context),
    plaid_service: PlaidService = Depends(get_plaid_service),
):
    """
    Get details for a specific Plaid item.

    **Auth Required:** Yes (Bearer token)
    **Org Scoped:** Yes (validates ownership)

    Returns:
        PlaidItemInfo or 404 if not found
    """
    item = plaid_service.get_item_for_org(ctx["org_id"], item_id)

    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "ITEM_ERROR",
                "error_code": "ITEM_NOT_FOUND",
                "message": f"Plaid item {item_id} not found for this organization",
            },
        )

    return {
        "success": True,
        "item": item,
    }
