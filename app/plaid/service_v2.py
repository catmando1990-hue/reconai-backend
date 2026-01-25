# app/plaid/service_v2.py
"""
Production Plaid Service v2 with Lifecycle Management

This service provides:
- Full product support (transactions, auth, balance, identity, income, assets, investments, liabilities)
- Canonical lifecycle state management
- Normalized error handling (no raw Plaid errors to frontend)
- Webhook-driven state transitions
- Idempotent data fetching

============================================================================
FROZEN NOTICE: Changes require RFC + Security Review + Migration Plan
============================================================================
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from plaid.api import plaid_api
from plaid.exceptions import ApiException
from plaid.model.accounts_balance_get_request import AccountsBalanceGetRequest
from plaid.model.accounts_get_request import AccountsGetRequest
from plaid.model.asset_report_create_request import AssetReportCreateRequest
from plaid.model.asset_report_create_request_options import AssetReportCreateRequestOptions
from plaid.model.auth_get_request import AuthGetRequest
from plaid.model.identity_get_request import IdentityGetRequest
from plaid.model.investments_holdings_get_request import InvestmentsHoldingsGetRequest
from plaid.model.investments_transactions_get_request import InvestmentsTransactionsGetRequest
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.liabilities_get_request import LiabilitiesGetRequest
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.transactions_sync_request import TransactionsSyncRequest

from app.db import DB_PATH
from app.plaid_client import get_plaid_client
from app.plaid.lifecycle import (
    PlaidLifecycle,
    build_lifecycle_response,
    error_to_lifecycle,
    normalize_plaid_error,
    webhook_to_lifecycle,
)
from app.plaid.products import (
    get_products,
    get_optional_products,
    get_country_codes,
    get_webhook_url,
    get_link_token_options,
    is_async_product,
)
from app.utils.encryption import get_encryption_service

logger = logging.getLogger(__name__)


# =============================================================================
# SERVICE CLASS
# =============================================================================

class PlaidServiceV2:
    """
    Production Plaid service with lifecycle management.
    
    All public methods return canonical lifecycle responses.
    NO RAW PLAID ERRORS IN RESPONSES.
    """

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._encryption = None
        self._plaid_client = None

    @property
    def encryption(self):
        if self._encryption is None:
            self._encryption = get_encryption_service()
        return self._encryption

    @property
    def plaid_client(self) -> plaid_api.PlaidApi:
        if self._plaid_client is None:
            self._plaid_client = get_plaid_client()
        return self._plaid_client

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _generate_request_id(self) -> str:
        return f"req_{uuid4().hex[:16]}"

    # =========================================================================
    # LINK TOKEN CREATION
    # =========================================================================

    def create_link_token(
        self,
        organization_id: str,
        user_id: str,
        redirect_uri: Optional[str] = None,
        entity_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a Plaid Link token with all enabled products.
        
        Products requested:
        - Core: transactions, auth
        - Extended: identity, assets, investments, liabilities
        - Optional: income
        
        Returns:
            Canonical lifecycle response with link_token
        """
        request_id = request_id or self._generate_request_id()

        try:
            client_user_id = f"{organization_id}:{user_id}"
            
            # Get all products
            products = get_products(include_extended=True)
            optional_products = get_optional_products()
            
            # Build request params
            request_params = {
                "user": LinkTokenCreateRequestUser(client_user_id=client_user_id),
                "client_name": "ReconAI",
                "products": products,
                "optional_products": optional_products,
                "country_codes": get_country_codes(),
                "language": "en",
            }
            
            # Add webhook URL
            webhook_url = get_webhook_url()
            if webhook_url:
                request_params["webhook"] = webhook_url
            
            # Add redirect URI for OAuth
            effective_redirect_uri = redirect_uri or os.getenv("PLAID_REDIRECT_URI")
            if effective_redirect_uri:
                request_params["redirect_uri"] = effective_redirect_uri
            
            request = LinkTokenCreateRequest(**request_params)
            response = self.plaid_client.link_token_create(request)
            
            logger.info(
                f"Link token created: org={organization_id} user={user_id} "
                f"products={[str(p) for p in products]}"
            )
            
            return build_lifecycle_response(
                success=True,
                lifecycle=PlaidLifecycle.CREATED,
                data={
                    "link_token": response.link_token,
                    "expiration": str(response.expiration) if response.expiration else None,
                    "products_requested": [str(p) for p in products],
                },
                request_id=request_id,
            )

        except ApiException as e:
            logger.error(f"Plaid link token error: {e}")
            return self._handle_plaid_exception(e, request_id)

        except Exception as e:
            logger.exception(f"Unexpected error creating link token: {e}")
            return build_lifecycle_response(
                success=False,
                lifecycle=PlaidLifecycle.ERROR,
                user_message="Unable to initialize bank connection. Please try again.",
                request_id=request_id,
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
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Exchange public token and create item with lifecycle state.
        
        Initial state: CREATED (waiting for first sync)
        
        Returns:
            Canonical lifecycle response with item_id
        """
        request_id = request_id or self._generate_request_id()

        try:
            exchange_request = ItemPublicTokenExchangeRequest(
                public_token=public_token
            )
            response = self.plaid_client.item_public_token_exchange(exchange_request)
            
            access_token = response.access_token
            item_id = response.item_id
            
            # Encrypt access token
            encrypted_token = self.encryption.encrypt(access_token)
            
            with self._get_conn() as conn:
                # Check for duplicate
                existing = conn.execute(
                    "SELECT id, organization_id FROM plaid_items WHERE item_id = ?",
                    (item_id,),
                ).fetchone()
                
                if existing:
                    logger.warning(
                        f"Duplicate Plaid item: item_id={item_id} "
                        f"existing_org={existing['organization_id']} new_org={organization_id}"
                    )
                    return build_lifecycle_response(
                        success=True,
                        lifecycle=PlaidLifecycle.READY,  # Existing item is likely ready
                        data={
                            "item_id": item_id,
                            "is_duplicate": True,
                            "institution_id": institution_id,
                            "institution_name": institution_name,
                        },
                        user_message="This bank account is already connected.",
                        request_id=request_id,
                    )
                
                # Create new item with CREATED lifecycle
                record_id = str(uuid4())
                webhook_url = get_webhook_url()
                
                conn.execute(
                    """
                    INSERT INTO plaid_items
                        (id, organization_id, entity_id, item_id, access_token_encrypted,
                         institution_id, institution_name, status, lifecycle, webhook_url, created_by)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record_id,
                        organization_id,
                        entity_id,
                        item_id,
                        encrypted_token,
                        institution_id,
                        institution_name,
                        "active",  # Legacy status
                        PlaidLifecycle.CREATED.value,  # New lifecycle
                        webhook_url,
                        user_id,
                    ),
                )
                conn.commit()
            
            logger.info(
                f"Plaid item created: org={organization_id} item={item_id} "
                f"institution={institution_name} lifecycle=CREATED"
            )
            
            return build_lifecycle_response(
                success=True,
                lifecycle=PlaidLifecycle.CREATED,
                data={
                    "item_id": item_id,
                    "is_duplicate": False,
                    "institution_id": institution_id,
                    "institution_name": institution_name,
                },
                request_id=request_id,
            )

        except ApiException as e:
            logger.error(f"Plaid exchange error: {e}")
            return self._handle_plaid_exception(e, request_id)

        except Exception as e:
            logger.exception(f"Unexpected error exchanging token: {e}")
            return build_lifecycle_response(
                success=False,
                lifecycle=PlaidLifecycle.ERROR,
                user_message="Unable to connect bank account. Please try again.",
                request_id=request_id,
            )

    # =========================================================================
    # LIFECYCLE STATE MANAGEMENT
    # =========================================================================

    def update_lifecycle(
        self,
        item_id: str,
        new_lifecycle: PlaidLifecycle,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> bool:
        """
        Update the lifecycle state of a Plaid item.
        
        Args:
            item_id: The Plaid item ID
            new_lifecycle: The new lifecycle state
            error_code: Optional error code (for ERROR/LOGIN_REQUIRED states)
            error_message: Optional error message (logged, not exposed)
            
        Returns:
            True if update succeeded
        """
        try:
            with self._get_conn() as conn:
                conn.execute(
                    """
                    UPDATE plaid_items
                    SET lifecycle = ?, error_code = ?, error_message = ?, updated_at = datetime('now')
                    WHERE item_id = ?
                    """,
                    (new_lifecycle.value, error_code, error_message, item_id),
                )
                conn.commit()
                
            logger.info(f"Lifecycle updated: item={item_id} -> {new_lifecycle.value}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update lifecycle: item={item_id} error={e}")
            return False

    def get_item_lifecycle(
        self,
        organization_id: str,
        item_id: str,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get the current lifecycle state of a Plaid item.
        
        Returns:
            Canonical lifecycle response with item data
        """
        request_id = request_id or self._generate_request_id()
        
        try:
            with self._get_conn() as conn:
                row = conn.execute(
                    """
                    SELECT id, item_id, institution_id, institution_name,
                           status, lifecycle, last_synced_at, error_code,
                           error_message, created_at, updated_at
                    FROM plaid_items
                    WHERE organization_id = ? AND item_id = ?
                    """,
                    (organization_id, item_id),
                ).fetchone()
                
                if not row:
                    return build_lifecycle_response(
                        success=False,
                        lifecycle=PlaidLifecycle.ERROR,
                        user_message="Bank connection not found.",
                        request_id=request_id,
                    )
                
                # Get lifecycle from DB or derive from legacy status
                lifecycle_str = row["lifecycle"] or row["status"]
                lifecycle = PlaidLifecycle.from_plaid_status(lifecycle_str)
                
                return build_lifecycle_response(
                    success=True,
                    lifecycle=lifecycle,
                    data={
                        "id": row["id"],
                        "item_id": row["item_id"],
                        "institution_id": row["institution_id"],
                        "institution_name": row["institution_name"],
                        "last_synced_at": row["last_synced_at"],
                        "created_at": row["created_at"],
                        "updated_at": row["updated_at"],
                    },
                    request_id=request_id,
                )
                
        except Exception as e:
            logger.exception(f"Error getting item lifecycle: {e}")
            return build_lifecycle_response(
                success=False,
                lifecycle=PlaidLifecycle.ERROR,
                user_message="Unable to retrieve bank connection status.",
                request_id=request_id,
            )

    # =========================================================================
    # WEBHOOK HANDLING
    # =========================================================================

    def process_webhook(
        self,
        webhook_type: str,
        webhook_code: str,
        item_id: str,
        payload: Dict[str, Any],
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Process a Plaid webhook and update lifecycle state.
        
        Handles:
        - TRANSACTIONS_READY -> READY
        - ASSETS_READY -> READY  
        - INVESTMENTS_READY -> READY
        - INCOME_VERIFICATION -> PROCESSING
        - ITEM_LOGIN_REQUIRED -> LOGIN_REQUIRED
        - ERROR -> ERROR
        
        Returns:
            Canonical lifecycle response with action taken
        """
        request_id = request_id or self._generate_request_id()
        
        try:
            with self._get_conn() as conn:
                # Look up item
                item = conn.execute(
                    "SELECT id, organization_id, lifecycle FROM plaid_items WHERE item_id = ?",
                    (item_id,),
                ).fetchone()
                
                if not item:
                    logger.warning(f"Webhook for unknown item: {item_id}")
                    return build_lifecycle_response(
                        success=True,
                        lifecycle=PlaidLifecycle.ERROR,
                        data={"action_taken": "ignored_unknown_item"},
                        request_id=request_id,
                    )
                
                # Store webhook event (idempotency)
                event_id = str(uuid4())
                conn.execute(
                    """
                    INSERT INTO plaid_webhook_events
                        (id, item_id, webhook_type, webhook_code, payload)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (event_id, item_id, webhook_type, webhook_code, json.dumps(payload)),
                )
                
                # Determine lifecycle transition
                new_lifecycle = webhook_to_lifecycle(webhook_type, webhook_code)
                action_taken = "no_action"
                
                if new_lifecycle:
                    # Update lifecycle
                    error_info = payload.get("error", {})
                    conn.execute(
                        """
                        UPDATE plaid_items
                        SET lifecycle = ?, error_code = ?, error_message = ?, updated_at = datetime('now')
                        WHERE item_id = ?
                        """,
                        (
                            new_lifecycle.value,
                            error_info.get("error_code"),
                            error_info.get("error_message"),
                            item_id,
                        ),
                    )
                    action_taken = f"lifecycle_updated_to_{new_lifecycle.value}"
                    
                    logger.info(
                        f"Webhook processed: type={webhook_type} code={webhook_code} "
                        f"item={item_id} -> {new_lifecycle.value}"
                    )
                else:
                    logger.info(
                        f"Webhook received (no lifecycle change): type={webhook_type} "
                        f"code={webhook_code} item={item_id}"
                    )
                
                # Mark webhook processed
                conn.execute(
                    """
                    UPDATE plaid_webhook_events
                    SET processed = 1, processed_at = datetime('now')
                    WHERE id = ?
                    """,
                    (event_id,),
                )
                
                conn.commit()
                
                current_lifecycle = new_lifecycle or PlaidLifecycle.from_plaid_status(
                    item["lifecycle"] or "active"
                )
                
                return build_lifecycle_response(
                    success=True,
                    lifecycle=current_lifecycle,
                    data={
                        "webhook_type": webhook_type,
                        "webhook_code": webhook_code,
                        "action_taken": action_taken,
                        "event_id": event_id,
                    },
                    request_id=request_id,
                )
                
        except Exception as e:
            logger.exception(f"Error processing webhook: {e}")
            return build_lifecycle_response(
                success=False,
                lifecycle=PlaidLifecycle.ERROR,
                user_message="Webhook processing failed.",
                request_id=request_id,
            )

    # =========================================================================
    # DATA FETCHING (LIFECYCLE-AWARE)
    # =========================================================================

    def sync_transactions(
        self,
        organization_id: str,
        item_id: str,
        count: int = 500,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Sync transactions with lifecycle-aware error handling.
        
        Only syncs if lifecycle is CREATED, PENDING, or READY.
        Updates lifecycle to READY on success, or appropriate error state.
        
        Returns:
            Canonical lifecycle response with transactions
        """
        request_id = request_id or self._generate_request_id()
        
        try:
            with self._get_conn() as conn:
                item = conn.execute(
                    """
                    SELECT id, access_token_encrypted, sync_cursor, status, lifecycle
                    FROM plaid_items
                    WHERE item_id = ? AND organization_id = ?
                    """,
                    (item_id, organization_id),
                ).fetchone()
                
                if not item:
                    return build_lifecycle_response(
                        success=False,
                        lifecycle=PlaidLifecycle.ERROR,
                        user_message="Bank connection not found.",
                        request_id=request_id,
                    )
                
                # Check lifecycle - don't sync if LOGIN_REQUIRED
                current_lifecycle = PlaidLifecycle.from_plaid_status(
                    item["lifecycle"] or item["status"]
                )
                
                if current_lifecycle == PlaidLifecycle.LOGIN_REQUIRED:
                    return build_lifecycle_response(
                        success=False,
                        lifecycle=PlaidLifecycle.LOGIN_REQUIRED,
                        user_message="Please reconnect your bank account to sync transactions.",
                        request_id=request_id,
                    )
                
                if current_lifecycle == PlaidLifecycle.ERROR:
                    return build_lifecycle_response(
                        success=False,
                        lifecycle=PlaidLifecycle.ERROR,
                        user_message="Bank connection has an error. Please reconnect.",
                        request_id=request_id,
                    )
            
            # Decrypt access token
            access_token = self.encryption.decrypt(item["access_token_encrypted"])
            
            # Build sync request
            sync_params = {
                "access_token": access_token,
                "count": min(count, 500),
            }
            if item["sync_cursor"]:
                sync_params["cursor"] = item["sync_cursor"]
            
            sync_request = TransactionsSyncRequest(**sync_params)
            response = self.plaid_client.transactions_sync(sync_request)
            
            # Parse transactions
            added = [self._parse_transaction(tx) for tx in response.added]
            modified = [self._parse_transaction(tx) for tx in response.modified]
            removed = [tx.transaction_id for tx in response.removed]
            accounts = [self._parse_account(acc) for acc in response.accounts]
            
            # Update cursor and lifecycle
            new_cursor = response.next_cursor
            has_more = response.has_more
            
            with self._get_conn() as conn:
                conn.execute(
                    """
                    UPDATE plaid_items
                    SET sync_cursor = ?, last_synced_at = datetime('now'),
                        lifecycle = ?, updated_at = datetime('now')
                    WHERE item_id = ? AND organization_id = ?
                    """,
                    (new_cursor, PlaidLifecycle.READY.value, item_id, organization_id),
                )
                conn.commit()
            
            logger.info(
                f"Transactions synced: org={organization_id} item={item_id} "
                f"added={len(added)} modified={len(modified)} removed={len(removed)}"
            )
            
            return build_lifecycle_response(
                success=True,
                lifecycle=PlaidLifecycle.READY,
                data={
                    "added": added,
                    "modified": modified,
                    "removed": removed,
                    "accounts": accounts,
                    "has_more": has_more,
                    "next_cursor": new_cursor,
                },
                request_id=request_id,
            )
            
        except ApiException as e:
            logger.error(f"Plaid sync error: {e}")
            return self._handle_plaid_exception(e, request_id, item_id)
            
        except Exception as e:
            logger.exception(f"Unexpected error syncing transactions: {e}")
            return build_lifecycle_response(
                success=False,
                lifecycle=PlaidLifecycle.ERROR,
                user_message="Unable to sync transactions. Please try again.",
                request_id=request_id,
            )

    def get_accounts(
        self,
        organization_id: str,
        item_id: str,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get accounts with balance information."""
        request_id = request_id or self._generate_request_id()
        
        try:
            item = self._get_item_for_sync(organization_id, item_id, request_id)
            if not item.get("success", False):
                return item
            
            access_token = self.encryption.decrypt(item["access_token_encrypted"])
            
            request = AccountsBalanceGetRequest(access_token=access_token)
            response = self.plaid_client.accounts_balance_get(request)
            
            accounts = [self._parse_account(acc) for acc in response.accounts]
            
            return build_lifecycle_response(
                success=True,
                lifecycle=PlaidLifecycle.READY,
                data={"accounts": accounts},
                request_id=request_id,
            )
            
        except ApiException as e:
            return self._handle_plaid_exception(e, request_id)
        except Exception as e:
            logger.exception(f"Error getting accounts: {e}")
            return build_lifecycle_response(
                success=False,
                lifecycle=PlaidLifecycle.ERROR,
                user_message="Unable to retrieve account information.",
                request_id=request_id,
            )

    def get_auth(
        self,
        organization_id: str,
        item_id: str,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get auth data (account and routing numbers)."""
        request_id = request_id or self._generate_request_id()
        
        try:
            item = self._get_item_for_sync(organization_id, item_id, request_id)
            if not item.get("success", False):
                return item
            
            access_token = self.encryption.decrypt(item["access_token_encrypted"])
            
            request = AuthGetRequest(access_token=access_token)
            response = self.plaid_client.auth_get(request)
            
            accounts = [self._parse_account(acc) for acc in response.accounts]
            numbers = {
                "ach": [self._parse_ach_numbers(n) for n in (response.numbers.ach or [])],
                "eft": [vars(n) for n in (response.numbers.eft or [])],
                "international": [vars(n) for n in (response.numbers.international or [])],
                "bacs": [vars(n) for n in (response.numbers.bacs or [])],
            }
            
            return build_lifecycle_response(
                success=True,
                lifecycle=PlaidLifecycle.READY,
                data={"accounts": accounts, "numbers": numbers},
                request_id=request_id,
            )
            
        except ApiException as e:
            return self._handle_plaid_exception(e, request_id)
        except Exception as e:
            logger.exception(f"Error getting auth: {e}")
            return build_lifecycle_response(
                success=False,
                lifecycle=PlaidLifecycle.ERROR,
                user_message="Unable to retrieve account numbers.",
                request_id=request_id,
            )

    def get_identity(
        self,
        organization_id: str,
        item_id: str,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get identity information for account holders."""
        request_id = request_id or self._generate_request_id()
        
        try:
            item = self._get_item_for_sync(organization_id, item_id, request_id)
            if not item.get("success", False):
                return item
            
            access_token = self.encryption.decrypt(item["access_token_encrypted"])
            
            request = IdentityGetRequest(access_token=access_token)
            response = self.plaid_client.identity_get(request)
            
            # Parse identity data (contains PII - handle carefully)
            accounts_with_identity = []
            for acc in response.accounts:
                acc_data = self._parse_account(acc)
                owners = []
                for owner in (acc.owners or []):
                    owners.append({
                        "names": list(owner.names) if owner.names else [],
                        "emails": [{"data": e.data, "type": str(e.type), "primary": e.primary} 
                                   for e in (owner.emails or [])],
                        "phone_numbers": [{"data": p.data, "type": str(p.type), "primary": p.primary}
                                          for p in (owner.phone_numbers or [])],
                        "addresses": [{"data": vars(a.data) if a.data else {}, "primary": a.primary}
                                      for a in (owner.addresses or [])],
                    })
                acc_data["owners"] = owners
                accounts_with_identity.append(acc_data)
            
            return build_lifecycle_response(
                success=True,
                lifecycle=PlaidLifecycle.READY,
                data={"accounts": accounts_with_identity},
                request_id=request_id,
            )
            
        except ApiException as e:
            return self._handle_plaid_exception(e, request_id)
        except Exception as e:
            logger.exception(f"Error getting identity: {e}")
            return build_lifecycle_response(
                success=False,
                lifecycle=PlaidLifecycle.ERROR,
                user_message="Unable to retrieve identity information.",
                request_id=request_id,
            )

    def get_investments(
        self,
        organization_id: str,
        item_id: str,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get investment holdings."""
        request_id = request_id or self._generate_request_id()
        
        try:
            item = self._get_item_for_sync(organization_id, item_id, request_id)
            if not item.get("success", False):
                return item
            
            access_token = self.encryption.decrypt(item["access_token_encrypted"])
            
            request = InvestmentsHoldingsGetRequest(access_token=access_token)
            response = self.plaid_client.investments_holdings_get(request)
            
            accounts = [self._parse_account(acc) for acc in response.accounts]
            holdings = [
                {
                    "account_id": h.account_id,
                    "security_id": h.security_id,
                    "quantity": float(h.quantity) if h.quantity else 0,
                    "institution_price": float(h.institution_price) if h.institution_price else 0,
                    "institution_value": float(h.institution_value) if h.institution_value else 0,
                    "cost_basis": float(h.cost_basis) if h.cost_basis else None,
                    "iso_currency_code": h.iso_currency_code,
                }
                for h in response.holdings
            ]
            securities = [
                {
                    "security_id": s.security_id,
                    "name": s.name,
                    "ticker_symbol": s.ticker_symbol,
                    "type": s.type,
                    "close_price": float(s.close_price) if s.close_price else None,
                    "iso_currency_code": s.iso_currency_code,
                }
                for s in response.securities
            ]
            
            return build_lifecycle_response(
                success=True,
                lifecycle=PlaidLifecycle.READY,
                data={
                    "accounts": accounts,
                    "holdings": holdings,
                    "securities": securities,
                },
                request_id=request_id,
            )
            
        except ApiException as e:
            return self._handle_plaid_exception(e, request_id)
        except Exception as e:
            logger.exception(f"Error getting investments: {e}")
            return build_lifecycle_response(
                success=False,
                lifecycle=PlaidLifecycle.ERROR,
                user_message="Unable to retrieve investment data.",
                request_id=request_id,
            )

    def get_liabilities(
        self,
        organization_id: str,
        item_id: str,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get liabilities (credit, loans, mortgages)."""
        request_id = request_id or self._generate_request_id()
        
        try:
            item = self._get_item_for_sync(organization_id, item_id, request_id)
            if not item.get("success", False):
                return item
            
            access_token = self.encryption.decrypt(item["access_token_encrypted"])
            
            request = LiabilitiesGetRequest(access_token=access_token)
            response = self.plaid_client.liabilities_get(request)
            
            accounts = [self._parse_account(acc) for acc in response.accounts]
            
            liabilities = {
                "credit": [],
                "mortgage": [],
                "student": [],
            }
            
            if response.liabilities.credit:
                liabilities["credit"] = [
                    {
                        "account_id": c.account_id,
                        "is_overdue": c.is_overdue,
                        "last_payment_amount": float(c.last_payment_amount) if c.last_payment_amount else None,
                        "last_payment_date": str(c.last_payment_date) if c.last_payment_date else None,
                        "last_statement_balance": float(c.last_statement_balance) if c.last_statement_balance else None,
                        "minimum_payment_amount": float(c.minimum_payment_amount) if c.minimum_payment_amount else None,
                        "next_payment_due_date": str(c.next_payment_due_date) if c.next_payment_due_date else None,
                    }
                    for c in response.liabilities.credit
                ]
            
            if response.liabilities.mortgage:
                liabilities["mortgage"] = [
                    {
                        "account_id": m.account_id,
                        "account_number": m.account_number,
                        "current_late_fee": float(m.current_late_fee) if m.current_late_fee else None,
                        "escrow_balance": float(m.escrow_balance) if m.escrow_balance else None,
                        "interest_rate_percentage": float(m.interest_rate.percentage) if m.interest_rate else None,
                        "last_payment_amount": float(m.last_payment_amount) if m.last_payment_amount else None,
                        "loan_term": m.loan_term,
                        "maturity_date": str(m.maturity_date) if m.maturity_date else None,
                        "next_monthly_payment": float(m.next_monthly_payment) if m.next_monthly_payment else None,
                        "origination_date": str(m.origination_date) if m.origination_date else None,
                        "origination_principal_amount": float(m.origination_principal_amount) if m.origination_principal_amount else None,
                        "past_due_amount": float(m.past_due_amount) if m.past_due_amount else None,
                    }
                    for m in response.liabilities.mortgage
                ]
            
            if response.liabilities.student:
                liabilities["student"] = [
                    {
                        "account_id": s.account_id,
                        "account_number": s.account_number,
                        "disbursement_dates": [str(d) for d in (s.disbursement_dates or [])],
                        "expected_payoff_date": str(s.expected_payoff_date) if s.expected_payoff_date else None,
                        "interest_rate_percentage": float(s.interest_rate_percentage) if s.interest_rate_percentage else None,
                        "is_overdue": s.is_overdue,
                        "last_payment_amount": float(s.last_payment_amount) if s.last_payment_amount else None,
                        "last_payment_date": str(s.last_payment_date) if s.last_payment_date else None,
                        "minimum_payment_amount": float(s.minimum_payment_amount) if s.minimum_payment_amount else None,
                        "next_payment_due_date": str(s.next_payment_due_date) if s.next_payment_due_date else None,
                        "origination_date": str(s.origination_date) if s.origination_date else None,
                        "origination_principal_amount": float(s.origination_principal_amount) if s.origination_principal_amount else None,
                        "outstanding_interest_amount": float(s.outstanding_interest_amount) if s.outstanding_interest_amount else None,
                    }
                    for s in response.liabilities.student
                ]
            
            return build_lifecycle_response(
                success=True,
                lifecycle=PlaidLifecycle.READY,
                data={
                    "accounts": accounts,
                    "liabilities": liabilities,
                },
                request_id=request_id,
            )
            
        except ApiException as e:
            return self._handle_plaid_exception(e, request_id)
        except Exception as e:
            logger.exception(f"Error getting liabilities: {e}")
            return build_lifecycle_response(
                success=False,
                lifecycle=PlaidLifecycle.ERROR,
                user_message="Unable to retrieve liability data.",
                request_id=request_id,
            )

    # =========================================================================
    # LIST ITEMS
    # =========================================================================

    def list_items(
        self,
        organization_id: str,
        entity_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List all Plaid items with lifecycle state."""
        request_id = request_id or self._generate_request_id()
        
        try:
            with self._get_conn() as conn:
                if entity_id:
                    rows = conn.execute(
                        """
                        SELECT id, item_id, institution_id, institution_name,
                               status, lifecycle, last_synced_at, error_code, created_at
                        FROM plaid_items
                        WHERE organization_id = ? AND entity_id = ?
                        ORDER BY created_at DESC
                        """,
                        (organization_id, entity_id),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT id, item_id, institution_id, institution_name,
                               status, lifecycle, last_synced_at, error_code, created_at
                        FROM plaid_items
                        WHERE organization_id = ?
                        ORDER BY created_at DESC
                        """,
                        (organization_id,),
                    ).fetchall()
                
            items = []
            for row in rows:
                lifecycle = PlaidLifecycle.from_plaid_status(
                    row["lifecycle"] or row["status"]
                )
                items.append({
                    "id": row["id"],
                    "item_id": row["item_id"],
                    "institution_id": row["institution_id"],
                    "institution_name": row["institution_name"],
                    "lifecycle": lifecycle.value,
                    "last_synced_at": row["last_synced_at"],
                    "created_at": row["created_at"],
                })
            
            # Determine overall lifecycle (worst state wins)
            if not items:
                overall_lifecycle = PlaidLifecycle.CREATED
            else:
                lifecycles = [PlaidLifecycle(i["lifecycle"]) for i in items]
                if PlaidLifecycle.ERROR in lifecycles:
                    overall_lifecycle = PlaidLifecycle.ERROR
                elif PlaidLifecycle.LOGIN_REQUIRED in lifecycles:
                    overall_lifecycle = PlaidLifecycle.LOGIN_REQUIRED
                elif PlaidLifecycle.PROCESSING in lifecycles:
                    overall_lifecycle = PlaidLifecycle.PROCESSING
                elif PlaidLifecycle.PENDING in lifecycles:
                    overall_lifecycle = PlaidLifecycle.PENDING
                elif PlaidLifecycle.CREATED in lifecycles:
                    overall_lifecycle = PlaidLifecycle.CREATED
                else:
                    overall_lifecycle = PlaidLifecycle.READY
            
            return build_lifecycle_response(
                success=True,
                lifecycle=overall_lifecycle,
                data={"items": items, "count": len(items)},
                request_id=request_id,
            )
            
        except Exception as e:
            logger.exception(f"Error listing items: {e}")
            return build_lifecycle_response(
                success=False,
                lifecycle=PlaidLifecycle.ERROR,
                user_message="Unable to retrieve connected accounts.",
                request_id=request_id,
            )

    # =========================================================================
    # REMOVE ITEM
    # =========================================================================

    def remove_item(
        self,
        organization_id: str,
        item_id: str,
        user_id: str,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Remove a Plaid item (unlink bank connection).
        
        This method:
        1. Revokes the access token with Plaid (best-effort)
        2. Deletes the item from the local database
        
        Args:
            organization_id: The organization owning the item
            item_id: The Plaid item ID to remove
            user_id: The user performing the removal (for audit)
            request_id: Request ID for tracing
            
        Returns:
            Canonical lifecycle response
        """
        request_id = request_id or self._generate_request_id()
        
        try:
            with self._get_conn() as conn:
                # Verify item exists and belongs to organization
                item = conn.execute(
                    """
                    SELECT id, access_token_encrypted, institution_name
                    FROM plaid_items
                    WHERE item_id = ? AND organization_id = ?
                    """,
                    (item_id, organization_id),
                ).fetchone()
                
                if not item:
                    return build_lifecycle_response(
                        success=False,
                        lifecycle=PlaidLifecycle.ERROR,
                        user_message="Bank connection not found.",
                        request_id=request_id,
                    )
                
                institution_name = item["institution_name"] or "Bank"
                
                # Best-effort: Revoke access token with Plaid
                plaid_revoke_success = False
                try:
                    access_token = self.encryption.decrypt(item["access_token_encrypted"])
                    from plaid.model.item_remove_request import ItemRemoveRequest
                    remove_request = ItemRemoveRequest(access_token=access_token)
                    self.plaid_client.item_remove(remove_request)
                    plaid_revoke_success = True
                    logger.info(f"Plaid access token revoked: item={item_id}")
                except ApiException as e:
                    # Log but don't fail - we still want to remove locally
                    logger.warning(f"Failed to revoke Plaid token (continuing): item={item_id} error={e}")
                except Exception as e:
                    logger.warning(f"Failed to revoke Plaid token (continuing): item={item_id} error={e}")
                
                # Delete from local database
                conn.execute(
                    "DELETE FROM plaid_items WHERE item_id = ? AND organization_id = ?",
                    (item_id, organization_id),
                )
                
                # Also clean up related webhook events
                conn.execute(
                    "DELETE FROM plaid_webhook_events WHERE item_id = ?",
                    (item_id,),
                )
                
                conn.commit()
            
            logger.info(
                f"Plaid item removed: org={organization_id} item={item_id} "
                f"institution={institution_name} plaid_revoked={plaid_revoke_success}"
            )
            
            return build_lifecycle_response(
                success=True,
                lifecycle=PlaidLifecycle.READY,  # Operation complete
                data={
                    "item_id": item_id,
                    "institution_name": institution_name,
                    "plaid_revoked": plaid_revoke_success,
                },
                user_message=f"{institution_name} has been disconnected.",
                request_id=request_id,
            )
            
        except Exception as e:
            logger.exception(f"Error removing item: {e}")
            return build_lifecycle_response(
                success=False,
                lifecycle=PlaidLifecycle.ERROR,
                user_message="Unable to remove bank connection. Please try again.",
                request_id=request_id,
            )

    # =========================================================================
    # INTERNAL HELPERS
    # =========================================================================

    def _get_item_for_sync(
        self,
        organization_id: str,
        item_id: str,
        request_id: str,
    ) -> Dict[str, Any]:
        """Get item for data fetch operations with lifecycle check."""
        with self._get_conn() as conn:
            item = conn.execute(
                """
                SELECT id, access_token_encrypted, sync_cursor, status, lifecycle
                FROM plaid_items
                WHERE item_id = ? AND organization_id = ?
                """,
                (item_id, organization_id),
            ).fetchone()
            
            if not item:
                return build_lifecycle_response(
                    success=False,
                    lifecycle=PlaidLifecycle.ERROR,
                    user_message="Bank connection not found.",
                    request_id=request_id,
                )
            
            lifecycle = PlaidLifecycle.from_plaid_status(
                item["lifecycle"] or item["status"]
            )
            
            if lifecycle == PlaidLifecycle.LOGIN_REQUIRED:
                return build_lifecycle_response(
                    success=False,
                    lifecycle=PlaidLifecycle.LOGIN_REQUIRED,
                    user_message="Please reconnect your bank account.",
                    request_id=request_id,
                )
            
            return {
                "success": True,
                "access_token_encrypted": item["access_token_encrypted"],
                "sync_cursor": item["sync_cursor"],
                "lifecycle": lifecycle,
            }

    def _handle_plaid_exception(
        self,
        e: ApiException,
        request_id: str,
        item_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Handle Plaid API exception and normalize to lifecycle response."""
        try:
            error_body = json.loads(e.body) if e.body else {}
            error_type = error_body.get("error_type", "API_ERROR")
            error_code = error_body.get("error_code", "UNKNOWN_ERROR")
            error_message = error_body.get("error_message", str(e))
            display_message = error_body.get("display_message")
            
            # Update item lifecycle if we have an item_id
            if item_id:
                lifecycle = error_to_lifecycle(error_code, error_type)
                self.update_lifecycle(item_id, lifecycle, error_code, error_message)
            
            return normalize_plaid_error(
                error_type=error_type,
                error_code=error_code,
                error_message=error_message,
                request_id=request_id,
                display_message=display_message,
            )
            
        except Exception:
            return build_lifecycle_response(
                success=False,
                lifecycle=PlaidLifecycle.ERROR,
                user_message="An error occurred with the bank connection.",
                request_id=request_id,
            )

    def _parse_transaction(self, tx) -> Dict[str, Any]:
        """Parse a Plaid transaction to dict."""
        return {
            "transaction_id": tx.transaction_id,
            "account_id": tx.account_id,
            "amount": float(tx.amount),
            "date": str(tx.date),
            "name": tx.name or "",
            "merchant_name": getattr(tx, "merchant_name", None),
            "category": list(tx.category) if tx.category else None,
            "category_id": tx.category_id,
            "pending": tx.pending,
            "payment_channel": getattr(tx, "payment_channel", None),
            "iso_currency_code": tx.iso_currency_code,
            "transaction_type": getattr(tx, "transaction_type", None),
        }

    def _parse_account(self, acc) -> Dict[str, Any]:
        """Parse a Plaid account to dict."""
        return {
            "account_id": acc.account_id,
            "name": acc.name,
            "official_name": getattr(acc, "official_name", None),
            "type": str(acc.type),
            "subtype": str(acc.subtype) if acc.subtype else None,
            "mask": acc.mask,
            "current_balance": float(acc.balances.current) if acc.balances.current else None,
            "available_balance": float(acc.balances.available) if acc.balances.available else None,
            "iso_currency_code": acc.balances.iso_currency_code,
        }

    def _parse_ach_numbers(self, n) -> Dict[str, Any]:
        """Parse ACH numbers to dict."""
        return {
            "account_id": n.account_id,
            "account": n.account,
            "routing": n.routing,
            "wire_routing": getattr(n, "wire_routing", None),
        }


# =============================================================================
# SINGLETON
# =============================================================================

_plaid_service_v2: Optional[PlaidServiceV2] = None


def get_plaid_service_v2() -> PlaidServiceV2:
    """Get or create the global PlaidServiceV2 instance."""
    global _plaid_service_v2
    if _plaid_service_v2 is None:
        _plaid_service_v2 = PlaidServiceV2()
    return _plaid_service_v2
