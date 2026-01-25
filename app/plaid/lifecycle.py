# app/plaid/lifecycle.py
"""
Canonical Plaid Item Lifecycle Model

This module defines the official lifecycle states for Plaid items and provides
error normalization to map Plaid API errors to user-friendly lifecycle states.

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

State Definitions:
- CREATED: Item record exists, token exchanged, initial sync not started
- PENDING: Initial sync in progress (transactions not yet available)
- PROCESSING: Async product data being prepared by Plaid
- READY: All requested products are available and synced
- LOGIN_REQUIRED: User must re-authenticate via Plaid Link
- ERROR: Unrecoverable error state (requires manual intervention)

============================================================================
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# LIFECYCLE ENUM
# =============================================================================

class PlaidLifecycle(str, Enum):
    """
    Canonical Plaid item lifecycle states.
    
    These states represent the user-facing status of a Plaid connection.
    Frontend should use these to display appropriate UI states.
    """
    CREATED = "created"           # Item created, initial sync pending
    PENDING = "pending"           # Initial sync in progress
    PROCESSING = "processing"     # Async products being prepared
    READY = "ready"               # All products available
    LOGIN_REQUIRED = "login_required"  # Re-authentication needed
    ERROR = "error"               # Unrecoverable error

    @classmethod
    def from_plaid_status(cls, status: str) -> "PlaidLifecycle":
        """Convert legacy PlaidItemStatus to lifecycle state."""
        mapping = {
            "active": cls.READY,
            "pending": cls.PENDING,
            "login_required": cls.LOGIN_REQUIRED,
            "error": cls.ERROR,
            "disconnected": cls.ERROR,
        }
        return mapping.get(status.lower(), cls.CREATED)


# =============================================================================
# PLAID ERROR CODES → LIFECYCLE MAPPING
# =============================================================================

# Plaid error codes that indicate LOGIN_REQUIRED
LOGIN_REQUIRED_ERRORS = frozenset([
    "ITEM_LOGIN_REQUIRED",
    "PENDING_EXPIRATION",
    "USER_PERMISSION_REVOKED",
    "INVALID_CREDENTIALS",
    "INVALID_MFA",
    "INVALID_SEND_METHOD",
    "ITEM_LOCKED",
    "INVALID_UPDATED_USERNAME",
    "MFA_NOT_SUPPORTED",
    "NO_ACCOUNTS",
    "INVALID_OTP",
    "INVALID_RECAPTCHA",
])

# Plaid error codes that indicate PROCESSING (async not ready)
PROCESSING_ERRORS = frozenset([
    "PRODUCT_NOT_READY",
    "PRODUCTS_NOT_SUPPORTED",
    "NO_INVESTMENT_ACCOUNTS",
    "NO_LIABILITY_ACCOUNTS",
    "VERIFICATION_EXPIRED",
])

# Plaid error codes that indicate permanent ERROR state
PERMANENT_ERROR_CODES = frozenset([
    "INVALID_ACCESS_TOKEN",
    "ITEM_NOT_FOUND",
    "ACCESS_NOT_GRANTED",
    "INSTITUTION_NOT_FOUND",
    "INSTITUTION_NOT_RESPONDING",
    "INSTITUTION_DOWN",
    "INSTITUTION_NO_LONGER_SUPPORTED",
    "INTERNAL_SERVER_ERROR",
    "RATE_LIMIT_EXCEEDED",
])


def error_to_lifecycle(error_code: str, error_type: str = "") -> PlaidLifecycle:
    """
    Map a Plaid error code to a lifecycle state.
    
    Args:
        error_code: The Plaid error_code from the API response
        error_type: The Plaid error_type from the API response
        
    Returns:
        The appropriate lifecycle state
    """
    error_code_upper = (error_code or "").upper()
    
    if error_code_upper in LOGIN_REQUIRED_ERRORS:
        return PlaidLifecycle.LOGIN_REQUIRED
    
    if error_code_upper in PROCESSING_ERRORS:
        return PlaidLifecycle.PROCESSING
    
    if error_code_upper in PERMANENT_ERROR_CODES:
        return PlaidLifecycle.ERROR
    
    # Default to ERROR for unknown error codes
    if error_code:
        logger.warning(f"Unknown Plaid error code '{error_code}' mapped to ERROR state")
        return PlaidLifecycle.ERROR
    
    return PlaidLifecycle.READY


# =============================================================================
# USER MESSAGE MAPPING
# =============================================================================

LIFECYCLE_USER_MESSAGES: Dict[PlaidLifecycle, str] = {
    PlaidLifecycle.CREATED: "Bank connection established. Waiting for initial data sync.",
    PlaidLifecycle.PENDING: "Your bank data is being synchronized. This may take a few minutes.",
    PlaidLifecycle.PROCESSING: "Processing additional financial data. This can take up to 24 hours.",
    PlaidLifecycle.READY: "Your bank account is connected and up to date.",
    PlaidLifecycle.LOGIN_REQUIRED: "Please reconnect your bank account to continue syncing.",
    PlaidLifecycle.ERROR: "There was an issue with your bank connection. Please try reconnecting.",
}


def get_user_message(lifecycle: PlaidLifecycle, custom_message: Optional[str] = None) -> str:
    """Get user-friendly message for a lifecycle state."""
    if custom_message:
        return custom_message
    return LIFECYCLE_USER_MESSAGES.get(lifecycle, "Unknown connection status.")


# =============================================================================
# WEBHOOK CODE → LIFECYCLE MAPPING
# =============================================================================

WEBHOOK_TO_LIFECYCLE: Dict[Tuple[str, str], PlaidLifecycle] = {
    # ITEM webhooks
    ("ITEM", "ERROR"): PlaidLifecycle.ERROR,
    ("ITEM", "PENDING_EXPIRATION"): PlaidLifecycle.LOGIN_REQUIRED,
    ("ITEM", "USER_PERMISSION_REVOKED"): PlaidLifecycle.LOGIN_REQUIRED,
    ("ITEM", "LOGIN_REPAIRED"): PlaidLifecycle.READY,
    
    # TRANSACTIONS webhooks
    ("TRANSACTIONS", "INITIAL_UPDATE"): PlaidLifecycle.PENDING,
    ("TRANSACTIONS", "HISTORICAL_UPDATE"): PlaidLifecycle.READY,
    ("TRANSACTIONS", "DEFAULT_UPDATE"): PlaidLifecycle.READY,
    ("TRANSACTIONS", "SYNC_UPDATES_AVAILABLE"): PlaidLifecycle.READY,
    
    # ASSETS webhooks
    ("ASSETS", "PRODUCT_READY"): PlaidLifecycle.READY,
    ("ASSETS", "ERROR"): PlaidLifecycle.PROCESSING,  # Retry-able
    
    # INVESTMENTS webhooks
    ("INVESTMENTS_TRANSACTIONS", "DEFAULT_UPDATE"): PlaidLifecycle.READY,
    
    # INCOME webhooks
    ("INCOME", "INCOME_VERIFICATION"): PlaidLifecycle.PROCESSING,
    ("INCOME", "INCOME_VERIFICATION_RISK_SIGNALS"): PlaidLifecycle.READY,
    
    # LIABILITIES webhooks
    ("LIABILITIES", "DEFAULT_UPDATE"): PlaidLifecycle.READY,
    
    # AUTH webhooks
    ("AUTH", "DEFAULT_UPDATE"): PlaidLifecycle.READY,
    ("AUTH", "AUTOMATICALLY_VERIFIED"): PlaidLifecycle.READY,
    ("AUTH", "VERIFICATION_EXPIRED"): PlaidLifecycle.LOGIN_REQUIRED,
}


def webhook_to_lifecycle(webhook_type: str, webhook_code: str) -> Optional[PlaidLifecycle]:
    """
    Map a webhook event to a lifecycle state update.
    
    Args:
        webhook_type: The Plaid webhook_type
        webhook_code: The Plaid webhook_code
        
    Returns:
        The lifecycle state to transition to, or None if no state change
    """
    key = (webhook_type.upper(), webhook_code.upper())
    return WEBHOOK_TO_LIFECYCLE.get(key)


# =============================================================================
# LIFECYCLE RESPONSE BUILDER
# =============================================================================

def build_lifecycle_response(
    success: bool,
    lifecycle: PlaidLifecycle,
    data: Optional[Dict[str, Any]] = None,
    user_message: Optional[str] = None,
    request_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build a canonical lifecycle-aware response.
    
    This is the standard response contract for all Plaid endpoints.
    Frontend should always expect this shape.
    
    Args:
        success: Whether the operation succeeded
        lifecycle: The current item lifecycle state
        data: Optional response data
        user_message: Optional custom user message
        request_id: The request ID for tracing
        
    Returns:
        Dict with: status, lifecycle, data, user_message, request_id
    """
    return {
        "status": "ok" if success else "error",
        "lifecycle": lifecycle.value,
        "data": data,
        "user_message": get_user_message(lifecycle, user_message),
        "request_id": request_id,
    }


def normalize_plaid_error(
    error_type: str,
    error_code: str,
    error_message: str,
    request_id: str,
    display_message: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Normalize a Plaid error into a lifecycle response.
    
    NO RAW PLAID ERRORS IN RESPONSES. This function maps Plaid errors
    to lifecycle states and user-friendly messages.
    
    Args:
        error_type: Plaid error_type
        error_code: Plaid error_code
        error_message: Plaid error_message (logged, not exposed)
        request_id: Request ID for tracing
        display_message: Optional user-facing message from Plaid
        
    Returns:
        Canonical lifecycle response dict
    """
    lifecycle = error_to_lifecycle(error_code, error_type)
    
    # Log the raw error for debugging (never expose to frontend)
    logger.warning(
        f"Plaid error normalized: type={error_type} code={error_code} "
        f"message={error_message} -> lifecycle={lifecycle.value}"
    )
    
    # Use Plaid's display_message if appropriate, otherwise our standard message
    user_message = display_message if display_message else None
    
    return build_lifecycle_response(
        success=False,
        lifecycle=lifecycle,
        data=None,
        user_message=user_message,
        request_id=request_id,
    )
