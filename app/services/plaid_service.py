# app/services/plaid_service.py
"""
Production-ready Plaid service with:
- Encrypted access token storage (AES-256-GCM)
- Organization-scoped item management
- Cursor-based transaction sync
- Immutable audit logging
- Duplicate detection
- Webhook signature verification

============================================================================
FROZEN AS OF 2024-01-20 (Phase 4 System Hardening)
============================================================================

DO NOT MODIFY THIS FILE WITHOUT FOLLOWING THE CHANGE PROCEDURE IN:
    app/plaid/FROZEN.md

Security Guarantees:
- AES-256-GCM token encryption (ENCRYPTION_KEY env var)
- HMAC-SHA256 webhook verification (PLAID_WEBHOOK_SECRET env var)
- Org-scoped data isolation
- Immutable audit trail

Any changes require: RFC + Security Review + Migration Plan
============================================================================
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from plaid.api import plaid_api
from plaid.exceptions import ApiException
from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products
from plaid.model.transactions_sync_request import TransactionsSyncRequest

from app.config import PLAID_CLIENT_ID, PLAID_ENV, PLAID_SECRET
from app.db import DB_PATH
from app.models.plaid import (
    CreateLinkTokenResponse,
    ExchangePublicTokenResponse,
    ListPlaidItemsResponse,
    PlaidAccount,
    PlaidAuditAction,
    PlaidErrorDetail,
    PlaidItemInfo,
    PlaidItemStatus,
    PlaidTransaction,
    TransactionsSyncResponse,
    WebhookResponse,
)
from app.plaid_client import get_plaid_client
from app.utils.encryption import get_encryption_service

logger = logging.getLogger(__name__)

# Plaid products we support
PLAID_PRODUCTS = [Products("transactions"), Products("auth")]


class PlaidService:
    """
    Production Plaid service with encryption and audit logging.

    All operations are:
    - Organization-scoped (multi-tenant)
    - Audit-logged (immutable)
    - Error-wrapped with request_id
    """

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._encryption = None
        self._plaid_client = None

    @property
    def encryption(self):
        """Lazy-load encryption service."""
        if self._encryption is None:
            self._encryption = get_encryption_service()
        return self._encryption

    @property
    def plaid_client(self) -> plaid_api.PlaidApi:
        """Lazy-load Plaid client."""
        if self._plaid_client is None:
            self._plaid_client = get_plaid_client()
        return self._plaid_client

    def _get_conn(self) -> sqlite3.Connection:
        """Get database connection with row factory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _generate_request_id(self) -> str:
        """Generate a unique request ID for tracing."""
        return f"req_{uuid4().hex[:16]}"

    def _log_audit(
        self,
        conn: sqlite3.Connection,
        organization_id: str,
        action: PlaidAuditAction,
        actor_id: str,
        request_id: str,
        item_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        """
        Write an immutable audit log entry.

        This is APPEND-ONLY - no updates or deletes permitted.
        """
        audit_id = str(uuid4())
        conn.execute(
            """
            INSERT INTO plaid_audit_log
                (id, organization_id, item_id, action, actor_id, request_id, details, ip_address, user_agent)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                audit_id,
                organization_id,
                item_id,
                action.value,
                actor_id,
                request_id,
                json.dumps(details or {}),
                ip_address,
                user_agent,
            ),
        )
        logger.info(
            f"Plaid audit: action={action.value} org={organization_id} item={item_id} request={request_id}"
        )

    def _make_error_response(
        self,
        request_id: str,
        error_type: str,
        error_code: str,
        error_message: str,
        display_message: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a structured error response."""
        return {
            "success": False,
            "request_id": request_id,
            "error": PlaidErrorDetail(
                error_type=error_type,
                error_code=error_code,
                error_message=error_message,
                display_message=display_message,
                request_id=request_id,
            ).model_dump(),
        }

    def _handle_plaid_exception(
        self, e: ApiException, request_id: str
    ) -> Dict[str, Any]:
        """Convert Plaid API exception to structured error response."""
        try:
            error_body = json.loads(e.body) if e.body else {}
            return self._make_error_response(
                request_id=request_id,
                error_type=error_body.get("error_type", "API_ERROR"),
                error_code=error_body.get("error_code", "UNKNOWN_ERROR"),
                error_message=error_body.get("error_message", str(e)),
                display_message=error_body.get("display_message"),
            )
        except Exception:
            return self._make_error_response(
                request_id=request_id,
                error_type="API_ERROR",
                error_code="PLAID_API_ERROR",
                error_message=str(e),
            )

    # =========================================================================
    # LINK TOKEN CREATION
    # =========================================================================

    def create_link_token(
        self,
        organization_id: str,
        user_id: str,
        redirect_uri: Optional[str] = None,
        entity_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> CreateLinkTokenResponse:
        """
        Create a Plaid Link token for the user.

        Args:
            organization_id: The organization making the request
            user_id: The authenticated user ID
            redirect_uri: OAuth redirect URI (required for production with OAuth banks)
            entity_id: Optional entity within organization
            ip_address: Client IP for audit logging
            user_agent: Client user agent for audit logging

        Returns:
            CreateLinkTokenResponse with link_token or error
        """
        request_id = self._generate_request_id()

        try:
            # Build client_user_id as org:user for scoping
            client_user_id = f"{organization_id}:{user_id}"

            # Base request parameters
            request_params = {
                "user": LinkTokenCreateRequestUser(client_user_id=client_user_id),
                "client_name": "ReconAI",
                "products": PLAID_PRODUCTS,
                "country_codes": [CountryCode("US")],
                "language": "en",
            }

            # Add webhook URL if configured
            webhook_url = os.getenv("PLAID_WEBHOOK_URL")
            if webhook_url:
                request_params["webhook"] = webhook_url

            # Add redirect_uri for OAuth (required for production)
            effective_redirect_uri = redirect_uri or os.getenv("PLAID_REDIRECT_URI")
            if effective_redirect_uri:
                request_params["redirect_uri"] = effective_redirect_uri

            request = LinkTokenCreateRequest(**request_params)
            response = self.plaid_client.link_token_create(request)

            # Log the operation (no sensitive data)
            with self._get_conn() as conn:
                self._log_audit(
                    conn=conn,
                    organization_id=organization_id,
                    action=PlaidAuditAction.ITEM_CREATED,
                    actor_id=user_id,
                    request_id=request_id,
                    details={
                        "event": "link_token_created",
                        "entity_id": entity_id,
                        "has_redirect_uri": bool(effective_redirect_uri),
                    },
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
                conn.commit()

            return CreateLinkTokenResponse(
                success=True,
                request_id=request_id,
                link_token=response.link_token,
                expiration=str(response.expiration) if response.expiration else None,
            )

        except ApiException as e:
            logger.error(f"Plaid link token error: {e}")
            error_response = self._handle_plaid_exception(e, request_id)
            return CreateLinkTokenResponse(**error_response)

        except Exception as e:
            logger.exception(f"Unexpected error creating link token: {e}")
            return CreateLinkTokenResponse(
                **self._make_error_response(
                    request_id=request_id,
                    error_type="INTERNAL_ERROR",
                    error_code="LINK_TOKEN_FAILED",
                    error_message=str(e),
                )
            )

    # =========================================================================
    # PUBLIC TOKEN EXCHANGE
    # =========================================================================

    def exchange_public_token(
        self,
        organization_id: str,
        user_id: str,
        public_token: str,
        institution_id: Optional[str] = None,
        institution_name: Optional[str] = None,
        entity_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> ExchangePublicTokenResponse:
        """
        Exchange a public token for an access token.

        The access token is encrypted at rest using AES-256-GCM.
        Detects duplicate items but does NOT auto-block or auto-merge.

        Args:
            organization_id: The organization making the request
            user_id: The authenticated user ID
            public_token: The Plaid public token from Link
            institution_id: Optional institution ID from Link
            institution_name: Optional institution name from Link
            entity_id: Optional entity within organization
            ip_address: Client IP for audit logging
            user_agent: Client user agent for audit logging

        Returns:
            ExchangePublicTokenResponse with item_id and is_duplicate flag
        """
        request_id = self._generate_request_id()

        try:
            # Exchange the token with Plaid
            exchange_request = ItemPublicTokenExchangeRequest(
                public_token=public_token
            )
            response = self.plaid_client.item_public_token_exchange(exchange_request)

            access_token = response.access_token
            item_id = response.item_id

            # Encrypt the access token
            encrypted_token = self.encryption.encrypt(access_token)

            with self._get_conn() as conn:
                # Check for duplicate (same item_id already exists)
                existing = conn.execute(
                    "SELECT id, organization_id FROM plaid_items WHERE item_id = ?",
                    (item_id,),
                ).fetchone()

                is_duplicate = existing is not None

                if is_duplicate:
                    # Item already exists - log but don't block
                    self._log_audit(
                        conn=conn,
                        organization_id=organization_id,
                        action=PlaidAuditAction.TOKEN_EXCHANGED,
                        actor_id=user_id,
                        request_id=request_id,
                        item_id=item_id,
                        details={
                            "is_duplicate": True,
                            "existing_org_id": existing["organization_id"],
                            "institution_id": institution_id,
                            "institution_name": institution_name,
                        },
                        ip_address=ip_address,
                        user_agent=user_agent,
                    )
                    conn.commit()

                    logger.warning(
                        f"Duplicate Plaid item detected: item_id={item_id} "
                        f"existing_org={existing['organization_id']} new_org={organization_id}"
                    )

                    return ExchangePublicTokenResponse(
                        success=True,
                        request_id=request_id,
                        item_id=item_id,
                        is_duplicate=True,
                        institution_id=institution_id,
                        institution_name=institution_name,
                    )

                # Create new item record
                record_id = str(uuid4())
                webhook_url = os.getenv("PLAID_WEBHOOK_URL")

                conn.execute(
                    """
                    INSERT INTO plaid_items
                        (id, organization_id, entity_id, item_id, access_token_encrypted,
                         institution_id, institution_name, status, webhook_url, created_by)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record_id,
                        organization_id,
                        entity_id,
                        item_id,
                        encrypted_token,
                        institution_id,
                        institution_name,
                        PlaidItemStatus.ACTIVE.value,
                        webhook_url,
                        user_id,
                    ),
                )

                # Log the token exchange
                self._log_audit(
                    conn=conn,
                    organization_id=organization_id,
                    action=PlaidAuditAction.TOKEN_EXCHANGED,
                    actor_id=user_id,
                    request_id=request_id,
                    item_id=item_id,
                    details={
                        "record_id": record_id,
                        "institution_id": institution_id,
                        "institution_name": institution_name,
                        "entity_id": entity_id,
                    },
                    ip_address=ip_address,
                    user_agent=user_agent,
                )

                conn.commit()

            logger.info(
                f"Plaid item created: org={organization_id} item={item_id} "
                f"institution={institution_name}"
            )

            return ExchangePublicTokenResponse(
                success=True,
                request_id=request_id,
                item_id=item_id,
                is_duplicate=False,
                institution_id=institution_id,
                institution_name=institution_name,
            )

        except ApiException as e:
            logger.error(f"Plaid exchange error: {e}")
            error_response = self._handle_plaid_exception(e, request_id)
            return ExchangePublicTokenResponse(**error_response)

        except Exception as e:
            logger.exception(f"Unexpected error exchanging token: {e}")
            return ExchangePublicTokenResponse(
                **self._make_error_response(
                    request_id=request_id,
                    error_type="INTERNAL_ERROR",
                    error_code="EXCHANGE_FAILED",
                    error_message=str(e),
                )
            )

    # =========================================================================
    # TRANSACTIONS SYNC (CURSOR-BASED)
    # =========================================================================

    def sync_transactions(
        self,
        organization_id: str,
        user_id: str,
        item_id: str,
        count: int = 500,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> TransactionsSyncResponse:
        """
        Sync transactions using cursor-based pagination.

        This is a MANUAL-ONLY operation - no background jobs or polling.
        Uses Plaid's /transactions/sync endpoint for efficient incremental sync.

        Args:
            organization_id: The organization making the request
            user_id: The authenticated user ID
            item_id: The Plaid item ID to sync
            count: Number of transactions to fetch (max 500)
            ip_address: Client IP for audit logging
            user_agent: Client user agent for audit logging

        Returns:
            TransactionsSyncResponse with added/modified/removed transactions
        """
        request_id = self._generate_request_id()

        try:
            with self._get_conn() as conn:
                # Look up the item and verify org ownership
                item = conn.execute(
                    """
                    SELECT id, access_token_encrypted, sync_cursor, status
                    FROM plaid_items
                    WHERE item_id = ? AND organization_id = ?
                    """,
                    (item_id, organization_id),
                ).fetchone()

                if not item:
                    return TransactionsSyncResponse(
                        **self._make_error_response(
                            request_id=request_id,
                            error_type="ITEM_ERROR",
                            error_code="ITEM_NOT_FOUND",
                            error_message=f"Plaid item {item_id} not found for this organization",
                            display_message="Bank connection not found. Please reconnect your account.",
                        )
                    )

                # Check item status
                if item["status"] == PlaidItemStatus.LOGIN_REQUIRED.value:
                    return TransactionsSyncResponse(
                        **self._make_error_response(
                            request_id=request_id,
                            error_type="ITEM_ERROR",
                            error_code="ITEM_LOGIN_REQUIRED",
                            error_message="Item requires re-authentication",
                            display_message="Please reconnect your bank account to continue syncing.",
                        )
                    )

                # Log sync start
                self._log_audit(
                    conn=conn,
                    organization_id=organization_id,
                    action=PlaidAuditAction.SYNC_STARTED,
                    actor_id=user_id,
                    request_id=request_id,
                    item_id=item_id,
                    details={"cursor": item["sync_cursor"], "count": count},
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
                conn.commit()

            # Decrypt access token
            access_token = self.encryption.decrypt(item["access_token_encrypted"])

            # Build sync request
            sync_request_params = {
                "access_token": access_token,
                "count": min(count, 500),
            }

            # Include cursor if we have one
            if item["sync_cursor"]:
                sync_request_params["cursor"] = item["sync_cursor"]

            sync_request = TransactionsSyncRequest(**sync_request_params)
            response = self.plaid_client.transactions_sync(sync_request)

            # Parse transactions
            added = [
                PlaidTransaction(
                    transaction_id=tx.transaction_id,
                    account_id=tx.account_id,
                    amount=float(tx.amount),
                    date=str(tx.date),
                    name=tx.name or "",
                    merchant_name=getattr(tx, "merchant_name", None),
                    category=list(tx.category) if tx.category else None,
                    category_id=tx.category_id,
                    pending=tx.pending,
                    payment_channel=getattr(tx, "payment_channel", None),
                    iso_currency_code=tx.iso_currency_code,
                    transaction_type=getattr(tx, "transaction_type", None),
                )
                for tx in response.added
            ]

            modified = [
                PlaidTransaction(
                    transaction_id=tx.transaction_id,
                    account_id=tx.account_id,
                    amount=float(tx.amount),
                    date=str(tx.date),
                    name=tx.name or "",
                    merchant_name=getattr(tx, "merchant_name", None),
                    category=list(tx.category) if tx.category else None,
                    category_id=tx.category_id,
                    pending=tx.pending,
                    payment_channel=getattr(tx, "payment_channel", None),
                    iso_currency_code=tx.iso_currency_code,
                    transaction_type=getattr(tx, "transaction_type", None),
                )
                for tx in response.modified
            ]

            removed = [tx.transaction_id for tx in response.removed]

            # Parse accounts
            accounts = [
                PlaidAccount(
                    account_id=acc.account_id,
                    name=acc.name,
                    official_name=getattr(acc, "official_name", None),
                    type=str(acc.type),
                    subtype=str(acc.subtype) if acc.subtype else None,
                    mask=acc.mask,
                    current_balance=float(acc.balances.current) if acc.balances.current else None,
                    available_balance=float(acc.balances.available) if acc.balances.available else None,
                    iso_currency_code=acc.balances.iso_currency_code,
                )
                for acc in response.accounts
            ]

            # Update cursor and last_synced_at
            new_cursor = response.next_cursor
            has_more = response.has_more

            with self._get_conn() as conn:
                conn.execute(
                    """
                    UPDATE plaid_items
                    SET sync_cursor = ?, last_synced_at = datetime('now'), updated_at = datetime('now')
                    WHERE item_id = ? AND organization_id = ?
                    """,
                    (new_cursor, item_id, organization_id),
                )

                # Log sync completion
                self._log_audit(
                    conn=conn,
                    organization_id=organization_id,
                    action=PlaidAuditAction.SYNC_COMPLETED,
                    actor_id=user_id,
                    request_id=request_id,
                    item_id=item_id,
                    details={
                        "added_count": len(added),
                        "modified_count": len(modified),
                        "removed_count": len(removed),
                        "has_more": has_more,
                        "new_cursor": new_cursor[:20] + "..." if new_cursor else None,
                    },
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
                conn.commit()

            logger.info(
                f"Plaid sync completed: org={organization_id} item={item_id} "
                f"added={len(added)} modified={len(modified)} removed={len(removed)}"
            )

            return TransactionsSyncResponse(
                success=True,
                request_id=request_id,
                added=added,
                modified=modified,
                removed=removed,
                next_cursor=new_cursor,
                has_more=has_more,
                accounts=accounts,
            )

        except ApiException as e:
            logger.error(f"Plaid sync error: {e}")

            # Log sync failure
            with self._get_conn() as conn:
                self._log_audit(
                    conn=conn,
                    organization_id=organization_id,
                    action=PlaidAuditAction.SYNC_FAILED,
                    actor_id=user_id,
                    request_id=request_id,
                    item_id=item_id,
                    details={"error": str(e)},
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
                conn.commit()

            error_response = self._handle_plaid_exception(e, request_id)
            return TransactionsSyncResponse(**error_response)

        except Exception as e:
            logger.exception(f"Unexpected error syncing transactions: {e}")

            # Log sync failure
            with self._get_conn() as conn:
                self._log_audit(
                    conn=conn,
                    organization_id=organization_id,
                    action=PlaidAuditAction.SYNC_FAILED,
                    actor_id=user_id,
                    request_id=request_id,
                    item_id=item_id,
                    details={"error": str(e)},
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
                conn.commit()

            return TransactionsSyncResponse(
                **self._make_error_response(
                    request_id=request_id,
                    error_type="INTERNAL_ERROR",
                    error_code="SYNC_FAILED",
                    error_message=str(e),
                )
            )

    # =========================================================================
    # WEBHOOK HANDLING
    # =========================================================================

    def verify_webhook_signature(
        self,
        body: bytes,
        plaid_verification: str,
    ) -> bool:
        """
        Verify Plaid webhook signature using HMAC-SHA256.

        Args:
            body: Raw request body bytes
            plaid_verification: Plaid-Verification header value

        Returns:
            True if signature is valid, False otherwise

        FAIL-CLOSED: Production requires PLAID_WEBHOOK_SECRET.
        Non-production allows unverified webhooks for local testing.
        """
        webhook_secret = os.getenv("PLAID_WEBHOOK_SECRET")
        env = os.getenv("ENVIRONMENT") or os.getenv("ENV") or os.getenv("NODE_ENV")

        if not webhook_secret:
            if env == "production":
                logger.error("PLAID_WEBHOOK_SECRET not configured in production - rejecting webhook")
                return False  # FAIL-CLOSED in production
            else:
                logger.warning("PLAID_WEBHOOK_SECRET not configured - skipping verification (non-production)")
                return True  # Allow in development/sandbox

        try:
            expected_signature = hmac.new(
                webhook_secret.encode("utf-8"),
                body,
                hashlib.sha256,
            ).hexdigest()

            return hmac.compare_digest(expected_signature, plaid_verification)
        except Exception as e:
            logger.error(f"Webhook signature verification failed: {e}")
            return False

    def process_webhook(
        self,
        webhook_type: str,
        webhook_code: str,
        item_id: str,
        payload: Dict[str, Any],
        ip_address: Optional[str] = None,
    ) -> WebhookResponse:
        """
        Process a Plaid webhook event.

        Only updates item status - no side effects.

        Args:
            webhook_type: Plaid webhook type (e.g., "ITEM", "TRANSACTIONS")
            webhook_code: Plaid webhook code (e.g., "ITEM_LOGIN_REQUIRED")
            item_id: The Plaid item ID
            payload: Full webhook payload
            ip_address: Source IP for audit logging

        Returns:
            WebhookResponse indicating action taken
        """
        request_id = self._generate_request_id()

        try:
            with self._get_conn() as conn:
                # Look up the item
                item = conn.execute(
                    "SELECT id, organization_id, status FROM plaid_items WHERE item_id = ?",
                    (item_id,),
                ).fetchone()

                if not item:
                    logger.warning(f"Webhook for unknown item: {item_id}")
                    return WebhookResponse(
                        success=True,
                        request_id=request_id,
                        webhook_type=webhook_type,
                        webhook_code=webhook_code,
                        action_taken="ignored_unknown_item",
                    )

                organization_id = item["organization_id"]

                # Store webhook event for idempotency
                event_id = str(uuid4())
                conn.execute(
                    """
                    INSERT INTO plaid_webhook_events
                        (id, item_id, webhook_type, webhook_code, payload)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (event_id, item_id, webhook_type, webhook_code, json.dumps(payload)),
                )

                # Log webhook receipt
                self._log_audit(
                    conn=conn,
                    organization_id=organization_id,
                    action=PlaidAuditAction.WEBHOOK_RECEIVED,
                    actor_id="system",
                    request_id=request_id,
                    item_id=item_id,
                    details={
                        "webhook_type": webhook_type,
                        "webhook_code": webhook_code,
                        "event_id": event_id,
                    },
                    ip_address=ip_address,
                )

                action_taken = "no_action"

                # Handle ITEM webhooks
                if webhook_type == "ITEM":
                    if webhook_code == "ERROR":
                        # Update item status to error
                        error_info = payload.get("error", {})
                        conn.execute(
                            """
                            UPDATE plaid_items
                            SET status = ?, error_code = ?, error_message = ?, updated_at = datetime('now')
                            WHERE item_id = ?
                            """,
                            (
                                PlaidItemStatus.ERROR.value,
                                error_info.get("error_code"),
                                error_info.get("error_message"),
                                item_id,
                            ),
                        )
                        action_taken = "status_updated_to_error"

                        self._log_audit(
                            conn=conn,
                            organization_id=organization_id,
                            action=PlaidAuditAction.ITEM_STATUS_CHANGED,
                            actor_id="system",
                            request_id=request_id,
                            item_id=item_id,
                            details={
                                "new_status": PlaidItemStatus.ERROR.value,
                                "error_code": error_info.get("error_code"),
                            },
                        )

                    elif webhook_code in ("PENDING_EXPIRATION", "USER_PERMISSION_REVOKED"):
                        # Mark item as requiring login
                        conn.execute(
                            """
                            UPDATE plaid_items
                            SET status = ?, error_code = ?, updated_at = datetime('now')
                            WHERE item_id = ?
                            """,
                            (PlaidItemStatus.LOGIN_REQUIRED.value, webhook_code, item_id),
                        )
                        action_taken = "status_updated_to_login_required"

                        self._log_audit(
                            conn=conn,
                            organization_id=organization_id,
                            action=PlaidAuditAction.ITEM_STATUS_CHANGED,
                            actor_id="system",
                            request_id=request_id,
                            item_id=item_id,
                            details={"new_status": PlaidItemStatus.LOGIN_REQUIRED.value},
                        )

                    elif webhook_code == "LOGIN_REPAIRED":
                        # Re-activate the item
                        conn.execute(
                            """
                            UPDATE plaid_items
                            SET status = ?, error_code = NULL, error_message = NULL, updated_at = datetime('now')
                            WHERE item_id = ?
                            """,
                            (PlaidItemStatus.ACTIVE.value, item_id),
                        )
                        action_taken = "status_updated_to_active"

                        self._log_audit(
                            conn=conn,
                            organization_id=organization_id,
                            action=PlaidAuditAction.ITEM_STATUS_CHANGED,
                            actor_id="system",
                            request_id=request_id,
                            item_id=item_id,
                            details={"new_status": PlaidItemStatus.ACTIVE.value},
                        )

                # Mark webhook as processed
                conn.execute(
                    """
                    UPDATE plaid_webhook_events
                    SET processed = 1, processed_at = datetime('now')
                    WHERE id = ?
                    """,
                    (event_id,),
                )

                # Log webhook processed
                self._log_audit(
                    conn=conn,
                    organization_id=organization_id,
                    action=PlaidAuditAction.WEBHOOK_PROCESSED,
                    actor_id="system",
                    request_id=request_id,
                    item_id=item_id,
                    details={
                        "event_id": event_id,
                        "action_taken": action_taken,
                    },
                )

                conn.commit()

            logger.info(
                f"Webhook processed: type={webhook_type} code={webhook_code} "
                f"item={item_id} action={action_taken}"
            )

            return WebhookResponse(
                success=True,
                request_id=request_id,
                webhook_type=webhook_type,
                webhook_code=webhook_code,
                action_taken=action_taken,
            )

        except Exception as e:
            logger.exception(f"Error processing webhook: {e}")

            return WebhookResponse(
                **self._make_error_response(
                    request_id=request_id,
                    error_type="INTERNAL_ERROR",
                    error_code="WEBHOOK_PROCESSING_FAILED",
                    error_message=str(e),
                )
            )

    # =========================================================================
    # ITEM MANAGEMENT
    # =========================================================================

    def list_items(
        self,
        organization_id: str,
        entity_id: Optional[str] = None,
    ) -> ListPlaidItemsResponse:
        """
        List all Plaid items for an organization.

        Args:
            organization_id: The organization ID
            entity_id: Optional entity filter

        Returns:
            ListPlaidItemsResponse with item list
        """
        request_id = self._generate_request_id()

        try:
            with self._get_conn() as conn:
                if entity_id:
                    rows = conn.execute(
                        """
                        SELECT id, item_id, institution_id, institution_name, status,
                               last_synced_at, error_code, error_message, created_at
                        FROM plaid_items
                        WHERE organization_id = ? AND entity_id = ?
                        ORDER BY created_at DESC
                        """,
                        (organization_id, entity_id),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT id, item_id, institution_id, institution_name, status,
                               last_synced_at, error_code, error_message, created_at
                        FROM plaid_items
                        WHERE organization_id = ?
                        ORDER BY created_at DESC
                        """,
                        (organization_id,),
                    ).fetchall()

            items = [
                PlaidItemInfo(
                    id=row["id"],
                    item_id=row["item_id"],
                    institution_id=row["institution_id"],
                    institution_name=row["institution_name"],
                    status=PlaidItemStatus(row["status"]),
                    last_synced_at=datetime.fromisoformat(row["last_synced_at"]) if row["last_synced_at"] else None,
                    error_code=row["error_code"],
                    error_message=row["error_message"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
                for row in rows
            ]

            return ListPlaidItemsResponse(
                success=True,
                request_id=request_id,
                items=items,
            )

        except Exception as e:
            logger.exception(f"Error listing items: {e}")
            return ListPlaidItemsResponse(
                **self._make_error_response(
                    request_id=request_id,
                    error_type="INTERNAL_ERROR",
                    error_code="LIST_ITEMS_FAILED",
                    error_message=str(e),
                )
            )

    def get_item_for_org(
        self,
        organization_id: str,
        item_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Get a Plaid item if it belongs to the organization.

        Args:
            organization_id: The organization ID
            item_id: The Plaid item ID

        Returns:
            Item record dict or None if not found/not owned
        """
        with self._get_conn() as conn:
            row = conn.execute(
                """
                SELECT id, item_id, institution_id, institution_name, status,
                       last_synced_at, error_code, error_message, created_at
                FROM plaid_items
                WHERE organization_id = ? AND item_id = ?
                """,
                (organization_id, item_id),
            ).fetchone()

            if row:
                return dict(row)
            return None


# Singleton instance
_plaid_service: Optional[PlaidService] = None


def get_plaid_service() -> PlaidService:
    """Get or create the global PlaidService instance."""
    global _plaid_service
    if _plaid_service is None:
        _plaid_service = PlaidService()
    return _plaid_service
