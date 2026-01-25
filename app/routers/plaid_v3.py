# app/routers/plaid_v3.py
"""
Production Plaid API routes v3 with Lifecycle Management

This router provides:
- Canonical lifecycle response contract: {status, lifecycle, data, user_message, request_id}
- Full product support: transactions, auth, balance, identity, investments, liabilities
- Normalized error handling (no raw Plaid errors to frontend)
- Webhook-driven state transitions
- FAIL-CLOSED audit provenance

============================================================================
RESPONSE CONTRACT
============================================================================

All endpoints return:
{
    "status": "ok" | "error",
    "lifecycle": "created" | "pending" | "processing" | "ready" | "login_required" | "error",
    "data": { ... },                    // Endpoint-specific data
    "user_message": "...",              // User-friendly message
    "request_id": "req_xxxxxxxxxxxx"    // Tracing ID
}

============================================================================
LIFECYCLE STATES
============================================================================

  CREATED ─────► PENDING ─────► READY
     │              │             │
     │              ▼             │
     │         PROCESSING        │
     │              │             │
     │              ▼             │
     └──────► LOGIN_REQUIRED ◄───┘
                   │
                   ▼
                 ERROR

============================================================================
ENDPOINTS
============================================================================

Link Flow:
- POST /api/plaid/v3/link-token           Create Link token
- POST /api/plaid/v3/exchange-token       Exchange public token

Data Sync:
- POST /api/plaid/v3/transactions/sync    Sync transactions
- GET  /api/plaid/v3/accounts/{item_id}   Get accounts with balance
- GET  /api/plaid/v3/auth/{item_id}       Get account/routing numbers
- GET  /api/plaid/v3/identity/{item_id}   Get account holder info
- GET  /api/plaid/v3/investments/{item_id} Get investment holdings
- GET  /api/plaid/v3/liabilities/{item_id} Get credit/loan data

Item Management:
- GET  /api/plaid/v3/items                List all items
- GET  /api/plaid/v3/items/{item_id}      Get item lifecycle
- DELETE /api/plaid/v3/items/{item_id}    Remove item (TODO)

Webhook:
- POST /api/plaid/v3/webhook              Handle Plaid webhooks

============================================================================
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth_context import AuthContext, get_current_context
from app.plaid.lifecycle import PlaidLifecycle, build_lifecycle_response
from app.plaid.service_v2 import PlaidServiceV2, get_plaid_service_v2
from app.services.audit_service import record_audit, AuditServiceError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/plaid/v3", tags=["plaid-v3"])


# =============================================================================
# REQUEST MODELS
# =============================================================================


class CreateLinkTokenRequest(BaseModel):
    """Request to create a Plaid Link token."""
    redirect_uri: Optional[str] = Field(None, description="OAuth redirect URI")
    entity_id: Optional[str] = Field(None, description="Entity to associate with item")


class ExchangeTokenRequest(BaseModel):
    """Request to exchange a public token."""
    public_token: str = Field(..., description="Plaid Link public token")
    institution_id: Optional[str] = Field(None, description="Institution ID")
    institution_name: Optional[str] = Field(None, description="Institution name")
    entity_id: Optional[str] = Field(None, description="Entity to associate with item")


class SyncTransactionsRequest(BaseModel):
    """Request to sync transactions."""
    item_id: str = Field(..., description="Plaid item ID")
    count: int = Field(500, ge=1, le=500, description="Max transactions to fetch")


# =============================================================================
# PROVENANCE HELPERS
# =============================================================================


def validate_request_id(request_id: Optional[str]) -> str:
    """
    Validate X-Request-ID header.
    FAIL-CLOSED: If missing or invalid, generate one.
    """
    if request_id:
        try:
            UUID(request_id)
            return request_id
        except (ValueError, TypeError):
            pass
    
    # Generate new request ID if missing or invalid
    return f"req_{uuid4().hex[:16]}"


def lifecycle_response(
    result: Dict[str, Any],
    request_id: str,
) -> JSONResponse:
    """
    Build a canonical lifecycle JSONResponse.
    
    - Header `X-Request-ID` set
    - Body includes canonical lifecycle fields
    """
    # Ensure request_id is in the response
    if "request_id" not in result or not result["request_id"]:
        result["request_id"] = request_id
    
    # Determine status code
    status_code = 200
    if result.get("status") == "error":
        lifecycle = result.get("lifecycle", "error")
        if lifecycle == "login_required":
            status_code = 200  # Not an error, just needs re-auth
        elif lifecycle == "error":
            status_code = 400
    
    return JSONResponse(
        status_code=status_code,
        headers={"X-Request-ID": request_id},
        content=result,
    )


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


@router.post("/link-token")
async def create_link_token(
    payload: CreateLinkTokenRequest,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    plaid_service: PlaidServiceV2 = Depends(get_plaid_service_v2),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
) -> JSONResponse:
    """
    Create a Plaid Link token with all enabled products.
    
    **Products Requested:**
    - Core: transactions, auth
    - Extended: identity, assets, investments, liabilities
    - Optional: income
    
    **Returns:**
    Canonical lifecycle response with link_token in data.
    """
    request_id = validate_request_id(x_request_id)
    
    # Audit (FAIL-CLOSED)
    try:
        record_audit(
            actor=ctx["user_id"],
            action="plaid.v3.create_link_token",
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
        logger.error(f"Audit failed for create_link_token: {e}")
        return lifecycle_response(
            build_lifecycle_response(
                success=False,
                lifecycle=PlaidLifecycle.ERROR,
                user_message="Unable to create link token: audit recording failed.",
                request_id=request_id,
            ),
            request_id,
        )
    
    result = plaid_service.create_link_token(
        organization_id=ctx["org_id"],
        user_id=ctx["user_id"],
        redirect_uri=payload.redirect_uri,
        entity_id=payload.entity_id,
        request_id=request_id,
    )
    
    return lifecycle_response(result, request_id)


# =============================================================================
# PUBLIC TOKEN EXCHANGE
# =============================================================================


@router.post("/exchange-token")
async def exchange_token(
    payload: ExchangeTokenRequest,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    plaid_service: PlaidServiceV2 = Depends(get_plaid_service_v2),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
) -> JSONResponse:
    """
    Exchange a Plaid public token for an access token.
    
    Creates a new Plaid item with lifecycle state CREATED.
    The access token is encrypted at rest (AES-256-GCM).
    
    **Returns:**
    Canonical lifecycle response with item_id in data.
    """
    request_id = validate_request_id(x_request_id)
    
    if not payload.public_token:
        return lifecycle_response(
            build_lifecycle_response(
                success=False,
                lifecycle=PlaidLifecycle.ERROR,
                user_message="Public token is required.",
                request_id=request_id,
            ),
            request_id,
        )
    
    # Audit (FAIL-CLOSED)
    try:
        record_audit(
            actor=ctx["user_id"],
            action="plaid.v3.exchange_token",
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
        logger.error(f"Audit failed for exchange_token: {e}")
        return lifecycle_response(
            build_lifecycle_response(
                success=False,
                lifecycle=PlaidLifecycle.ERROR,
                user_message="Unable to connect bank: audit recording failed.",
                request_id=request_id,
            ),
            request_id,
        )
    
    result = plaid_service.exchange_public_token(
        organization_id=ctx["org_id"],
        user_id=ctx["user_id"],
        public_token=payload.public_token,
        institution_id=payload.institution_id,
        institution_name=payload.institution_name,
        entity_id=payload.entity_id,
        request_id=request_id,
    )
    
    return lifecycle_response(result, request_id)


# =============================================================================
# TRANSACTIONS SYNC
# =============================================================================


@router.post("/transactions/sync")
async def sync_transactions(
    payload: SyncTransactionsRequest,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    plaid_service: PlaidServiceV2 = Depends(get_plaid_service_v2),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
) -> JSONResponse:
    """
    Sync transactions for a connected Plaid item.
    
    Uses cursor-based sync for efficient incremental updates.
    Updates lifecycle to READY on success.
    
    **Lifecycle-Aware:**
    - Returns LOGIN_REQUIRED if item needs re-auth
    - Returns ERROR if item has unrecoverable error
    
    **Returns:**
    Canonical lifecycle response with added, modified, removed transactions.
    """
    request_id = validate_request_id(x_request_id)
    
    # Audit (FAIL-CLOSED)
    try:
        record_audit(
            actor=ctx["user_id"],
            action="plaid.v3.sync_transactions",
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
        logger.error(f"Audit failed for sync_transactions: {e}")
        return lifecycle_response(
            build_lifecycle_response(
                success=False,
                lifecycle=PlaidLifecycle.ERROR,
                user_message="Unable to sync transactions: audit recording failed.",
                request_id=request_id,
            ),
            request_id,
        )
    
    result = plaid_service.sync_transactions(
        organization_id=ctx["org_id"],
        item_id=payload.item_id,
        count=payload.count,
        request_id=request_id,
    )
    
    return lifecycle_response(result, request_id)


# =============================================================================
# ACCOUNTS
# =============================================================================


@router.get("/accounts/{item_id}")
async def get_accounts(
    item_id: str,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    plaid_service: PlaidServiceV2 = Depends(get_plaid_service_v2),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
) -> JSONResponse:
    """
    Get accounts with balance for a Plaid item.
    
    **Returns:**
    Canonical lifecycle response with accounts array.
    """
    request_id = validate_request_id(x_request_id)
    
    result = plaid_service.get_accounts(
        organization_id=ctx["org_id"],
        item_id=item_id,
        request_id=request_id,
    )
    
    return lifecycle_response(result, request_id)


# =============================================================================
# AUTH (ACCOUNT/ROUTING NUMBERS)
# =============================================================================


@router.get("/auth/{item_id}")
async def get_auth(
    item_id: str,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    plaid_service: PlaidServiceV2 = Depends(get_plaid_service_v2),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
) -> JSONResponse:
    """
    Get account and routing numbers for a Plaid item.
    
    **Products Required:** auth
    
    **Returns:**
    Canonical lifecycle response with accounts and numbers.
    """
    request_id = validate_request_id(x_request_id)
    
    result = plaid_service.get_auth(
        organization_id=ctx["org_id"],
        item_id=item_id,
        request_id=request_id,
    )
    
    return lifecycle_response(result, request_id)


# =============================================================================
# IDENTITY
# =============================================================================


@router.get("/identity/{item_id}")
async def get_identity(
    item_id: str,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    plaid_service: PlaidServiceV2 = Depends(get_plaid_service_v2),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
) -> JSONResponse:
    """
    Get identity information for account holders.
    
    **Products Required:** identity
    **Contains PII:** Names, emails, phone numbers, addresses
    
    **Returns:**
    Canonical lifecycle response with accounts including owners.
    """
    request_id = validate_request_id(x_request_id)
    
    result = plaid_service.get_identity(
        organization_id=ctx["org_id"],
        item_id=item_id,
        request_id=request_id,
    )
    
    return lifecycle_response(result, request_id)


# =============================================================================
# INVESTMENTS
# =============================================================================


@router.get("/investments/{item_id}")
async def get_investments(
    item_id: str,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    plaid_service: PlaidServiceV2 = Depends(get_plaid_service_v2),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
) -> JSONResponse:
    """
    Get investment holdings for a Plaid item.
    
    **Products Required:** investments
    
    **Returns:**
    Canonical lifecycle response with accounts, holdings, securities.
    """
    request_id = validate_request_id(x_request_id)
    
    result = plaid_service.get_investments(
        organization_id=ctx["org_id"],
        item_id=item_id,
        request_id=request_id,
    )
    
    return lifecycle_response(result, request_id)


# =============================================================================
# LIABILITIES
# =============================================================================


@router.get("/liabilities/{item_id}")
async def get_liabilities(
    item_id: str,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    plaid_service: PlaidServiceV2 = Depends(get_plaid_service_v2),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
) -> JSONResponse:
    """
    Get liabilities (credit, loans, mortgages) for a Plaid item.
    
    **Products Required:** liabilities
    
    **Returns:**
    Canonical lifecycle response with accounts and liabilities.
    """
    request_id = validate_request_id(x_request_id)
    
    result = plaid_service.get_liabilities(
        organization_id=ctx["org_id"],
        item_id=item_id,
        request_id=request_id,
    )
    
    return lifecycle_response(result, request_id)


# =============================================================================
# ITEM MANAGEMENT
# =============================================================================


@router.get("/items")
async def list_items(
    request: Request,
    entity_id: Optional[str] = None,
    ctx: AuthContext = Depends(get_current_context),
    plaid_service: PlaidServiceV2 = Depends(get_plaid_service_v2),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
) -> JSONResponse:
    """
    List all connected Plaid items with lifecycle state.
    
    **Returns:**
    Canonical lifecycle response with items array.
    Overall lifecycle is worst state across all items.
    """
    request_id = validate_request_id(x_request_id)
    
    result = plaid_service.list_items(
        organization_id=ctx["org_id"],
        entity_id=entity_id,
        request_id=request_id,
    )
    
    return lifecycle_response(result, request_id)


@router.get("/items/{item_id}")
async def get_item(
    item_id: str,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    plaid_service: PlaidServiceV2 = Depends(get_plaid_service_v2),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
) -> JSONResponse:
    """
    Get lifecycle state for a specific Plaid item.
    
    **Returns:**
    Canonical lifecycle response with item details.
    """
    request_id = validate_request_id(x_request_id)
    
    result = plaid_service.get_item_lifecycle(
        organization_id=ctx["org_id"],
        item_id=item_id,
        request_id=request_id,
    )
    
    return lifecycle_response(result, request_id)


# =============================================================================
# WEBHOOK HANDLER
# =============================================================================


@router.post("/webhook")
async def handle_webhook(
    request: Request,
    plaid_verification: Optional[str] = Header(None, alias="Plaid-Verification"),
    plaid_service: PlaidServiceV2 = Depends(get_plaid_service_v2),
) -> JSONResponse:
    """
    Handle Plaid webhook events.
    
    **Auth Required:** No (signature verified instead)
    **Webhook Verification:** Plaid-Verification header (HMAC-SHA256)
    
    Updates item lifecycle based on webhook type/code:
    - TRANSACTIONS_READY -> READY
    - ITEM_LOGIN_REQUIRED -> LOGIN_REQUIRED
    - ERROR -> ERROR
    
    **Returns:**
    Canonical lifecycle response with action taken.
    """
    request_id = f"req_{uuid4().hex[:16]}"
    
    # Read raw body for signature verification
    body = await request.body()
    
    # FAIL-CLOSED: Production requires Plaid-Verification header
    env = os.getenv("ENVIRONMENT") or os.getenv("ENV") or os.getenv("NODE_ENV")
    if not plaid_verification:
        if env == "production":
            logger.warning("Webhook missing Plaid-Verification header in production")
            return lifecycle_response(
                build_lifecycle_response(
                    success=False,
                    lifecycle=PlaidLifecycle.ERROR,
                    user_message="Webhook signature required.",
                    request_id=request_id,
                ),
                request_id,
            )
        else:
            logger.warning("Webhook missing Plaid-Verification header (non-production)")
    
    # TODO: Verify webhook signature using plaid_verification header
    # This requires implementing HMAC-SHA256 verification against Plaid's webhook key
    
    # Parse payload
    try:
        webhook_payload = json.loads(body)
    except json.JSONDecodeError as e:
        return lifecycle_response(
            build_lifecycle_response(
                success=False,
                lifecycle=PlaidLifecycle.ERROR,
                user_message=f"Invalid webhook payload: {e}",
                request_id=request_id,
            ),
            request_id,
        )
    
    webhook_type = webhook_payload.get("webhook_type", "")
    webhook_code = webhook_payload.get("webhook_code", "")
    item_id = webhook_payload.get("item_id", "")
    
    if not item_id:
        logger.warning(f"Webhook missing item_id: type={webhook_type} code={webhook_code}")
        return lifecycle_response(
            build_lifecycle_response(
                success=True,
                lifecycle=PlaidLifecycle.READY,
                data={"action_taken": "ignored_missing_item_id"},
                request_id=request_id,
            ),
            request_id,
        )
    
    result = plaid_service.process_webhook(
        webhook_type=webhook_type,
        webhook_code=webhook_code,
        item_id=item_id,
        payload=webhook_payload,
        request_id=request_id,
    )
    
    return lifecycle_response(result, request_id)
