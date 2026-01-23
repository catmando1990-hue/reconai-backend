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
import os
from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse

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
)
from app.services.plaid_service import PlaidService, get_plaid_service
from app.services.audit_service import record_audit, AuditServiceError

logger = logging.getLogger(__name__)


# =============================================================================
# AUDIT PROVENANCE HELPERS (FAIL-CLOSED)
# =============================================================================


def validate_request_id(request_id: Optional[str]) -> str:
    """
    Validate X-Request-ID header.

    FAIL-CLOSED: If missing or invalid, abort the request.

    Args:
        request_id: The X-Request-ID header value

    Returns:
        Validated request_id string

    Raises:
        HTTPException: If request_id is missing or invalid
    """
    if not request_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "PROVENANCE_ERROR",
                "error_code": "MISSING_REQUEST_ID",
                "message": "X-Request-ID header is required for audit provenance",
            },
        )

    # Validate UUID format
    try:
        UUID(request_id)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "PROVENANCE_ERROR",
                "error_code": "INVALID_REQUEST_ID",
                "message": "X-Request-ID must be a valid UUID",
            },
        )

    return request_id


def provenance_response(
    payload: dict,
    request_id: str,
    status_code: int = 200,
) -> JSONResponse:
    """
    Canonical provenance response builder.

    CHECKLIST (FAIL IF ANY MISSING):
    - Header `X-Request-ID` set ✓
    - Body includes `request_id` ✓

    Args:
        payload: Response payload dict
        request_id: The validated request_id
        status_code: HTTP status code (default: 200)

    Returns:
        JSONResponse with:
        - X-Request-ID header echoed
        - request_id in body
    """
    # CHECKLIST ITEM 1: Ensure request_id is in the body
    payload["request_id"] = request_id

    # CHECKLIST ITEM 2: Return with X-Request-ID header
    return JSONResponse(
        status_code=status_code,
        headers={"X-Request-ID": request_id},
        content=payload,
    )


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


@router.post("/create-link-token")
async def create_link_token(
    payload: CreateLinkTokenRequest,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    plaid_service: PlaidService = Depends(get_plaid_service),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
) -> JSONResponse:
    """
    Create a Plaid Link token for connecting a bank account.

    **Auth Required:** Yes (Bearer token)
    **Org Scoped:** Yes
    **Audit Provenance:** FAIL-CLOSED - X-Request-ID required

    The link token is used to initialize Plaid Link in the frontend.
    Products enabled: transactions, auth, balance

    Returns:
        JSONResponse with link_token, expiration, and X-Request-ID header
    """
    # PART 1: INGRESS PROVENANCE - Validate X-Request-ID (FAIL-CLOSED)
    request_id = validate_request_id(x_request_id)

    # PART 2: AUDIT WRITE - Write audit synchronously via canonical audit_store (FAIL-CLOSED)
    try:
        record_audit(
            actor=ctx["user_id"],
            action="plaid.create_link_token",
            entity="plaid",
            entity_id=ctx["org_id"],
            payload={
                "entity_id": payload.entity_id,
                "has_redirect_uri": bool(payload.redirect_uri),
                "ip_address": _get_client_ip(request),
            },
            request_id=request_id,
        )
    except AuditServiceError as e:
        # FAIL-CLOSED: Audit failure aborts the request
        logger.error(f"Audit failed for create_link_token: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "AUDIT_FAILED",
                "error_code": "AUDIT_WRITE_FAILED",
                "message": "Link token creation aborted: audit recording failed",
                "request_id": request_id,
            },
        ) from e

    # Call Plaid service
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
        # Return error with provenance
        return provenance_response(
            payload={
                "success": False,
                "error": response.error.model_dump() if response.error else None,
            },
            request_id=request_id,
            status_code=400,
        )

    # PART 3: EGRESS PROVENANCE - Echo request_id in header and body
    return provenance_response(
        payload={
            "success": True,
            "link_token": response.link_token,
            "expiration": response.expiration,
        },
        request_id=request_id,
    )


# =============================================================================
# PUBLIC TOKEN EXCHANGE
# =============================================================================


@router.post("/exchange-public-token")
async def exchange_public_token(
    payload: ExchangePublicTokenRequest,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    plaid_service: PlaidService = Depends(get_plaid_service),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
) -> JSONResponse:
    """
    Exchange a Plaid public token for an access token.

    **Auth Required:** Yes (Bearer token)
    **Org Scoped:** Yes
    **Audit Provenance:** FAIL-CLOSED - X-Request-ID required

    The access token is encrypted at rest (AES-256-GCM) and stored
    with the organization. This endpoint detects duplicate items and
    returns is_duplicate=true if the same bank account is already connected.

    **Note:** Duplicate detection is server-side only. The endpoint does NOT
    auto-block or auto-merge duplicates - the client should handle the
    is_duplicate flag appropriately.

    Audit logged: token_exchanged, item_created

    Returns:
        JSONResponse with item_id, is_duplicate flag, and X-Request-ID header
    """
    # PART 1: INGRESS PROVENANCE - Validate X-Request-ID (FAIL-CLOSED)
    request_id = validate_request_id(x_request_id)

    if not payload.public_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "VALIDATION_ERROR",
                "error_code": "MISSING_PUBLIC_TOKEN",
                "message": "public_token is required",
                "request_id": request_id,
            },
        )

    # PART 2: AUDIT WRITE - Write audit synchronously via canonical audit_store (FAIL-CLOSED)
    try:
        record_audit(
            actor=ctx["user_id"],
            action="plaid.exchange_public_token",
            entity="plaid",
            entity_id=ctx["org_id"],
            payload={
                "institution_id": payload.institution_id,
                "institution_name": payload.institution_name,
                "entity_id": payload.entity_id,
                "ip_address": _get_client_ip(request),
            },
            request_id=request_id,
        )
    except AuditServiceError as e:
        # FAIL-CLOSED: Audit failure aborts the request
        logger.error(f"Audit failed for exchange_public_token: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "AUDIT_FAILED",
                "error_code": "AUDIT_WRITE_FAILED",
                "message": "Token exchange aborted: audit recording failed",
                "request_id": request_id,
            },
        ) from e

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
        # Return error with provenance
        return provenance_response(
            payload={
                "success": False,
                "error": response.error.model_dump() if response.error else None,
            },
            request_id=request_id,
            status_code=400,
        )

    # P0 HARD FAIL: item_id is REQUIRED on success - no silent fallbacks
    if not response.item_id:
        logger.error(
            f"Token exchange succeeded but item_id missing: org={ctx['org_id']}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "PLAID_ERROR",
                "error_code": "MISSING_ITEM_ID",
                "message": "Plaid exchange succeeded but item_id was not returned",
                "request_id": request_id,
            },
        )

    # PART 3: EGRESS PROVENANCE - Echo request_id in header and body
    return provenance_response(
        payload={
            "success": True,
            "item_id": response.item_id,
            "is_duplicate": response.is_duplicate,
            "institution_id": response.institution_id,
            "institution_name": response.institution_name,
        },
        request_id=request_id,
    )


# =============================================================================
# TRANSACTIONS SYNC
# =============================================================================


@router.post("/transactions/sync")
async def sync_transactions(
    payload: TransactionsSyncRequest,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    plaid_service: PlaidService = Depends(get_plaid_service),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
) -> JSONResponse:
    """
    Sync transactions for a connected Plaid item.

    **Auth Required:** Yes (Bearer token)
    **Org Scoped:** Yes (validates item belongs to org)
    **Audit Provenance:** FAIL-CLOSED - X-Request-ID required

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
        JSONResponse with transactions, pagination info, and X-Request-ID header
    """
    # PART 1: INGRESS PROVENANCE - Validate X-Request-ID (FAIL-CLOSED)
    request_id = validate_request_id(x_request_id)

    if not payload.item_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "VALIDATION_ERROR",
                "error_code": "MISSING_ITEM_ID",
                "message": "item_id is required",
                "request_id": request_id,
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
                "request_id": request_id,
            },
        )

    # PART 2: AUDIT WRITE - Write audit synchronously via canonical audit_store (FAIL-CLOSED)
    try:
        record_audit(
            actor=ctx["user_id"],
            action="plaid.sync_transactions",
            entity="plaid",
            entity_id=payload.item_id,
            payload={
                "org_id": ctx["org_id"],
                "count": payload.count,
                "ip_address": _get_client_ip(request),
            },
            request_id=request_id,
        )
    except AuditServiceError as e:
        # FAIL-CLOSED: Audit failure aborts the request
        logger.error(f"Audit failed for sync_transactions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "AUDIT_FAILED",
                "error_code": "AUDIT_WRITE_FAILED",
                "message": "Transaction sync aborted: audit recording failed",
                "request_id": request_id,
            },
        ) from e

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
        # Return error with provenance
        return provenance_response(
            payload={
                "success": False,
                "error": response.error.model_dump() if response.error else None,
            },
            request_id=request_id,
            status_code=400,
        )

    # PART 3: EGRESS PROVENANCE - Echo request_id in header and body
    return provenance_response(
        payload={
            "success": True,
            "added": [tx.model_dump() for tx in response.added],
            "modified": [tx.model_dump() for tx in response.modified],
            "removed": response.removed,
            "next_cursor": response.next_cursor,
            "has_more": response.has_more,
            "accounts": [acc.model_dump() for acc in response.accounts],
        },
        request_id=request_id,
    )


# =============================================================================
# WEBHOOK ENDPOINT
# =============================================================================


@router.post("/webhook")
async def handle_webhook(
    request: Request,
    plaid_verification: Optional[str] = Header(None, alias="Plaid-Verification"),
    plaid_service: PlaidService = Depends(get_plaid_service),
) -> JSONResponse:
    """
    Handle Plaid webhook events.

    **Auth Required:** No (but signature verified)
    **Webhook Verification:** Plaid-Verification header (HMAC-SHA256)
    **Provenance:** Internal request_id generated (webhooks don't have X-Request-ID)

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
        JSONResponse with provenance (X-Request-ID header and body field)
    """
    # Generate internal request_id for webhooks (they don't have X-Request-ID)
    request_id = str(uuid4())

    # Read raw body for signature verification
    body = await request.body()

    # FAIL-CLOSED: Production requires Plaid-Verification header
    env = os.getenv("ENVIRONMENT") or os.getenv("ENV") or os.getenv("NODE_ENV")
    if not plaid_verification:
        if env == "production":
            logger.warning("Webhook missing Plaid-Verification header in production")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "error": "WEBHOOK_ERROR",
                    "error_code": "MISSING_SIGNATURE",
                    "message": "Plaid-Verification header required in production",
                    "request_id": request_id,
                },
            )
        else:
            logger.warning("Webhook missing Plaid-Verification header (non-production, allowing)")

    # Verify signature if header present
    if plaid_verification:
        if not plaid_service.verify_webhook_signature(body, plaid_verification):
            logger.warning("Webhook signature verification failed")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "error": "WEBHOOK_ERROR",
                    "error_code": "INVALID_SIGNATURE",
                    "message": "Webhook signature verification failed",
                    "request_id": request_id,
                },
            )

    # Parse payload
    try:
        webhook_payload = json.loads(body)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "WEBHOOK_ERROR",
                "error_code": "INVALID_PAYLOAD",
                "message": f"Invalid JSON payload: {e}",
                "request_id": request_id,
            },
        )

    webhook_type = webhook_payload.get("webhook_type", "")
    webhook_code = webhook_payload.get("webhook_code", "")
    item_id = webhook_payload.get("item_id", "")

    if not item_id:
        logger.warning(f"Webhook missing item_id: type={webhook_type} code={webhook_code}")
        return provenance_response(
            payload={
                "success": True,
                "webhook_type": webhook_type,
                "webhook_code": webhook_code,
                "action_taken": "ignored_missing_item_id",
            },
            request_id=request_id,
        )

    response = plaid_service.process_webhook(
        webhook_type=webhook_type,
        webhook_code=webhook_code,
        item_id=item_id,
        payload=webhook_payload,
        ip_address=_get_client_ip(request),
    )

    # Return via canonical provenance_response
    return provenance_response(
        payload={
            "success": response.success,
            "webhook_type": response.webhook_type,
            "webhook_code": response.webhook_code,
            "action_taken": response.action_taken,
        },
        request_id=request_id,
    )


# =============================================================================
# ITEM MANAGEMENT
# =============================================================================


@router.get("/items")
async def list_items(
    request: Request,
    entity_id: Optional[str] = None,
    ctx: AuthContext = Depends(get_current_context),
    plaid_service: PlaidService = Depends(get_plaid_service),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
) -> JSONResponse:
    """
    List all connected Plaid items for the organization.

    **Auth Required:** Yes (Bearer token)
    **Org Scoped:** Yes
    **Audit Provenance:** FAIL-CLOSED - X-Request-ID required

    Returns all bank connections for the organization, optionally
    filtered by entity_id.

    Returns:
        JSONResponse with list of PlaidItemInfo and X-Request-ID header
    """
    # PART 1: INGRESS PROVENANCE - Validate X-Request-ID (FAIL-CLOSED)
    request_id = validate_request_id(x_request_id)

    # PART 2: AUDIT WRITE - Write audit synchronously via canonical audit_store (FAIL-CLOSED)
    try:
        record_audit(
            actor=ctx["user_id"],
            action="plaid.list_items",
            entity="plaid",
            entity_id=ctx["org_id"],
            payload={
                "entity_id": entity_id,
                "ip_address": _get_client_ip(request),
            },
            request_id=request_id,
        )
    except AuditServiceError as e:
        # FAIL-CLOSED: Audit failure aborts the request
        logger.error(f"Audit failed for list_items: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "AUDIT_FAILED",
                "error_code": "AUDIT_WRITE_FAILED",
                "message": "List items aborted: audit recording failed",
                "request_id": request_id,
            },
        ) from e

    response = plaid_service.list_items(
        organization_id=ctx["org_id"],
        entity_id=entity_id,
    )

    # PART 3: EGRESS PROVENANCE - Echo request_id in header and body
    return provenance_response(
        payload={
            "success": response.success,
            "items": [item.model_dump(mode='json') for item in response.items] if response.items else [],
        },
        request_id=request_id,
    )


@router.get("/items/{item_id}")
async def get_item(
    item_id: str,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    plaid_service: PlaidService = Depends(get_plaid_service),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
) -> JSONResponse:
    """
    Get details for a specific Plaid item.

    **Auth Required:** Yes (Bearer token)
    **Org Scoped:** Yes (validates ownership)
    **Audit Provenance:** FAIL-CLOSED - X-Request-ID required

    Returns:
        JSONResponse with PlaidItemInfo and X-Request-ID header, or 404 if not found
    """
    # PART 1: INGRESS PROVENANCE - Validate X-Request-ID (FAIL-CLOSED)
    request_id = validate_request_id(x_request_id)

    # PART 2: AUDIT WRITE - Write audit synchronously via canonical audit_store (FAIL-CLOSED)
    try:
        record_audit(
            actor=ctx["user_id"],
            action="plaid.get_item",
            entity="plaid",
            entity_id=item_id,
            payload={
                "org_id": ctx["org_id"],
                "ip_address": _get_client_ip(request),
            },
            request_id=request_id,
        )
    except AuditServiceError as e:
        # FAIL-CLOSED: Audit failure aborts the request
        logger.error(f"Audit failed for get_item: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "AUDIT_FAILED",
                "error_code": "AUDIT_WRITE_FAILED",
                "message": "Get item aborted: audit recording failed",
                "request_id": request_id,
            },
        ) from e

    item = plaid_service.get_item_for_org(ctx["org_id"], item_id)

    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "ITEM_ERROR",
                "error_code": "ITEM_NOT_FOUND",
                "message": f"Plaid item {item_id} not found for this organization",
                "request_id": request_id,
            },
        )

    # PART 3: EGRESS PROVENANCE - Echo request_id in header and body
    return provenance_response(
        payload={
            "success": True,
            "item": item,
        },
        request_id=request_id,
    )
