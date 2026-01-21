# app/models/plaid.py
"""
Plaid integration models for production-ready implementation.

Supports:
- Org-scoped Plaid items with encrypted access tokens
- Cursor-based transaction sync
- Webhook event handling
- Immutable audit logging
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# =============================================================================
# ENUMS
# =============================================================================

class PlaidItemStatus(str, Enum):
    """Status of a Plaid item connection."""
    ACTIVE = "active"
    LOGIN_REQUIRED = "login_required"
    PENDING = "pending"
    ERROR = "error"
    DISCONNECTED = "disconnected"


class PlaidWebhookType(str, Enum):
    """Plaid webhook types we handle."""
    TRANSACTIONS = "TRANSACTIONS"
    ITEM = "ITEM"
    AUTH = "AUTH"


class PlaidWebhookCode(str, Enum):
    """Plaid webhook codes we handle."""
    # Transactions webhooks
    INITIAL_UPDATE = "INITIAL_UPDATE"
    HISTORICAL_UPDATE = "HISTORICAL_UPDATE"
    DEFAULT_UPDATE = "DEFAULT_UPDATE"
    TRANSACTIONS_REMOVED = "TRANSACTIONS_REMOVED"
    SYNC_UPDATES_AVAILABLE = "SYNC_UPDATES_AVAILABLE"

    # Item webhooks
    ERROR = "ERROR"
    LOGIN_REPAIRED = "LOGIN_REPAIRED"
    PENDING_EXPIRATION = "PENDING_EXPIRATION"
    USER_PERMISSION_REVOKED = "USER_PERMISSION_REVOKED"
    WEBHOOK_UPDATE_ACKNOWLEDGED = "WEBHOOK_UPDATE_ACKNOWLEDGED"


class PlaidAuditAction(str, Enum):
    """Audit log action types for Plaid operations."""
    TOKEN_EXCHANGED = "token_exchanged"
    ITEM_CREATED = "item_created"
    ITEM_STATUS_CHANGED = "item_status_changed"
    SYNC_STARTED = "sync_started"
    SYNC_COMPLETED = "sync_completed"
    SYNC_FAILED = "sync_failed"
    WEBHOOK_RECEIVED = "webhook_received"
    WEBHOOK_PROCESSED = "webhook_processed"
    ITEM_DISCONNECTED = "item_disconnected"


# =============================================================================
# REQUEST MODELS
# =============================================================================

class CreateLinkTokenRequest(BaseModel):
    """Request to create a Plaid Link token."""
    redirect_uri: Optional[str] = None
    entity_id: Optional[str] = None  # Optional entity within organization


class ExchangePublicTokenRequest(BaseModel):
    """Request to exchange a public token for an access token."""
    public_token: str = Field(..., min_length=1)
    institution_id: Optional[str] = None
    institution_name: Optional[str] = None
    entity_id: Optional[str] = None


class TransactionsSyncRequest(BaseModel):
    """Request to sync transactions for a Plaid item."""
    item_id: str = Field(..., min_length=1)
    count: int = Field(default=500, ge=1, le=500)


class PlaidWebhookPayload(BaseModel):
    """Incoming Plaid webhook payload."""
    webhook_type: str
    webhook_code: str
    item_id: str
    error: Optional[Dict[str, Any]] = None
    new_transactions: Optional[int] = None
    removed_transactions: Optional[List[str]] = None
    consent_expiration_time: Optional[str] = None
    environment: Optional[str] = None


# =============================================================================
# RESPONSE MODELS
# =============================================================================

class PlaidErrorDetail(BaseModel):
    """Structured error detail for Plaid operations."""
    error_type: str
    error_code: str
    error_message: str
    display_message: Optional[str] = None
    request_id: Optional[str] = None


class PlaidApiResponse(BaseModel):
    """Base response wrapper with request_id for tracing."""
    success: bool
    request_id: str
    error: Optional[PlaidErrorDetail] = None


class CreateLinkTokenResponse(PlaidApiResponse):
    """Response from link token creation."""
    link_token: Optional[str] = None
    expiration: Optional[str] = None


class ExchangePublicTokenResponse(PlaidApiResponse):
    """Response from public token exchange."""
    item_id: Optional[str] = None
    is_duplicate: bool = False
    institution_id: Optional[str] = None
    institution_name: Optional[str] = None


class PlaidAccount(BaseModel):
    """Plaid account information."""
    account_id: str
    name: str
    official_name: Optional[str] = None
    type: str
    subtype: Optional[str] = None
    mask: Optional[str] = None
    current_balance: Optional[float] = None
    available_balance: Optional[float] = None
    iso_currency_code: Optional[str] = None


class PlaidTransaction(BaseModel):
    """Plaid transaction for sync response."""
    transaction_id: str
    account_id: str
    amount: float
    date: str
    name: str
    merchant_name: Optional[str] = None
    category: Optional[List[str]] = None
    category_id: Optional[str] = None
    pending: bool = False
    payment_channel: Optional[str] = None
    iso_currency_code: Optional[str] = None
    transaction_type: Optional[str] = None


class TransactionsSyncResponse(PlaidApiResponse):
    """Response from transactions sync."""
    added: List[PlaidTransaction] = Field(default_factory=list)
    modified: List[PlaidTransaction] = Field(default_factory=list)
    removed: List[str] = Field(default_factory=list)
    next_cursor: Optional[str] = None
    has_more: bool = False
    accounts: List[PlaidAccount] = Field(default_factory=list)


class WebhookResponse(PlaidApiResponse):
    """Response from webhook processing."""
    webhook_type: Optional[str] = None
    webhook_code: Optional[str] = None
    action_taken: Optional[str] = None


# =============================================================================
# DATABASE MODELS (for type hints)
# =============================================================================

class PlaidItemRecord(BaseModel):
    """Plaid item record stored in database."""
    id: str
    organization_id: str
    entity_id: Optional[str] = None
    item_id: str  # Plaid's item_id
    access_token_encrypted: str
    institution_id: Optional[str] = None
    institution_name: Optional[str] = None
    status: PlaidItemStatus = PlaidItemStatus.PENDING
    sync_cursor: Optional[str] = None
    last_synced_at: Optional[datetime] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    webhook_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    created_by: str


class PlaidAuditLogRecord(BaseModel):
    """Immutable audit log record for Plaid operations."""
    id: str
    organization_id: str
    item_id: Optional[str] = None
    action: PlaidAuditAction
    actor_id: str
    request_id: str
    details: Dict[str, Any] = Field(default_factory=dict)
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: datetime


# =============================================================================
# PLAID ITEM RESPONSE
# =============================================================================

class PlaidItemInfo(BaseModel):
    """Public-facing Plaid item info (no sensitive data)."""
    id: str
    item_id: str
    institution_id: Optional[str] = None
    institution_name: Optional[str] = None
    status: PlaidItemStatus
    last_synced_at: Optional[datetime] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime


class ListPlaidItemsResponse(PlaidApiResponse):
    """Response listing all Plaid items for an organization."""
    items: List[PlaidItemInfo] = Field(default_factory=list)
