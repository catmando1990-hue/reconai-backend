# app/services/core_sync_triggers.py
"""
CORE Sync Triggers - Auto-hydration triggers for CORE state.

This module provides NON-BLOCKING trigger functions that schedule CORE sync
in the background when Plaid data changes. These triggers:
- Run asynchronously (never block the request thread)
- Are idempotent (safe to call multiple times)
- Capture errors (never crash the request)
- Do NOT require frontend involvement

Trigger Points:
- on_plaid_item_connected: Bank account newly connected
- on_plaid_item_refreshed: Transactions synced for existing item
- on_plaid_item_reconnected: Item re-authenticated after error

CRITICAL: These triggers run in background threads. Failures are logged
and recorded in sync metadata but NEVER propagate to the caller.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

# =============================================================================
# BACKGROUND TASK MANAGER
# =============================================================================

# Track running syncs to prevent duplicate concurrent syncs per org
_running_syncs: Dict[str, datetime] = {}
_running_syncs_lock = threading.Lock()

# Cooldown between auto-retries (1 hour)
AUTO_RETRY_COOLDOWN_SECONDS = 3600

# Track last auto-retry attempt per org
_last_retry_attempt: Dict[str, datetime] = {}
_last_retry_lock = threading.Lock()


def _is_sync_running(organization_id: str) -> bool:
    """Check if a sync is currently running for this org."""
    with _running_syncs_lock:
        if organization_id in _running_syncs:
            # Check if it's stale (running for more than 10 minutes = stuck)
            started = _running_syncs[organization_id]
            if datetime.utcnow() - started > timedelta(minutes=10):
                # Clear stale entry
                del _running_syncs[organization_id]
                return False
            return True
        return False


def _mark_sync_started(organization_id: str) -> bool:
    """
    Mark sync as started. Returns False if already running.

    This provides idempotency - only one sync per org at a time.
    """
    with _running_syncs_lock:
        if organization_id in _running_syncs:
            started = _running_syncs[organization_id]
            if datetime.utcnow() - started < timedelta(minutes=10):
                return False  # Already running
        _running_syncs[organization_id] = datetime.utcnow()
        return True


def _mark_sync_completed(organization_id: str) -> None:
    """Mark sync as completed."""
    with _running_syncs_lock:
        _running_syncs.pop(organization_id, None)


def _can_auto_retry(organization_id: str) -> bool:
    """Check if auto-retry is allowed (respects cooldown)."""
    with _last_retry_lock:
        last_attempt = _last_retry_attempt.get(organization_id)
        if last_attempt is None:
            return True
        elapsed = (datetime.utcnow() - last_attempt).total_seconds()
        return elapsed >= AUTO_RETRY_COOLDOWN_SECONDS


def _record_retry_attempt(organization_id: str) -> None:
    """Record that an auto-retry was attempted."""
    with _last_retry_lock:
        _last_retry_attempt[organization_id] = datetime.utcnow()


# =============================================================================
# BACKGROUND SYNC RUNNER
# =============================================================================


def _run_sync_in_background(
    organization_id: str,
    trigger_source: str,
    user_id: Optional[str] = None,
) -> None:
    """
    Run CORE sync in a background thread.

    This function:
    - Never blocks the caller
    - Captures all exceptions
    - Updates sync metadata on success/failure
    - Is idempotent (skips if already running)
    """
    def _sync_task():
        request_id = f"auto_{uuid4().hex[:12]}"

        try:
            # Import here to avoid circular imports
            from app.services.core_sync import get_core_sync_service

            if not _mark_sync_started(organization_id):
                logger.info(
                    f"CORE sync already running for org={organization_id}, skipping"
                )
                return

            logger.info(
                f"CORE auto-sync started: org={organization_id} "
                f"trigger={trigger_source} request_id={request_id}"
            )

            core_service = get_core_sync_service()
            result = core_service.sync_organization(
                organization_id=organization_id,
                user_id=user_id or "system",
                ip_address=None,
                user_agent=f"CORE-AutoSync/{trigger_source}",
            )

            if result.get('success'):
                logger.info(
                    f"CORE auto-sync completed: org={organization_id} "
                    f"transactions={result.get('transactions_synced', 0)} "
                    f"request_id={request_id}"
                )
            else:
                logger.warning(
                    f"CORE auto-sync failed: org={organization_id} "
                    f"error={result.get('error')} request_id={request_id}"
                )

        except Exception as e:
            # CRITICAL: Never let exceptions escape the background thread
            logger.exception(
                f"CORE auto-sync exception: org={organization_id} "
                f"trigger={trigger_source} error={e}"
            )
            # Record failure in metadata
            try:
                from app.services.core_sync import get_core_sync_service
                core_service = get_core_sync_service()
                core_service._update_sync_status(
                    organization_id=organization_id,
                    status='failed',
                    request_id=request_id,
                    error_message=f"Auto-sync exception: {str(e)}"
                )
            except Exception as meta_error:
                logger.error(f"Failed to record sync failure: {meta_error}")
        finally:
            _mark_sync_completed(organization_id)

    # Start background thread (daemon=True so it doesn't block shutdown)
    thread = threading.Thread(target=_sync_task, daemon=True)
    thread.start()

    logger.debug(
        f"CORE sync scheduled in background: org={organization_id} trigger={trigger_source}"
    )


# =============================================================================
# TRIGGER FUNCTIONS (Called from Plaid lifecycle points)
# =============================================================================


def on_plaid_item_connected(
    organization_id: str,
    item_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> None:
    """
    Trigger CORE sync when a new Plaid item is connected.

    Called after successful token exchange (new bank connection).

    Args:
        organization_id: The organization that connected the item
        item_id: The newly connected Plaid item ID (for logging)
        user_id: The user who performed the connection

    This function returns immediately. Sync runs in background.
    """
    logger.info(
        f"CORE trigger: item_connected org={organization_id} item={item_id}"
    )
    _run_sync_in_background(
        organization_id=organization_id,
        trigger_source="item_connected",
        user_id=user_id,
    )


def on_plaid_item_refreshed(
    organization_id: str,
    item_id: Optional[str] = None,
    transactions_added: int = 0,
    user_id: Optional[str] = None,
) -> None:
    """
    Trigger CORE sync when transactions are refreshed for an item.

    Called after successful transaction sync.

    Args:
        organization_id: The organization that refreshed transactions
        item_id: The Plaid item ID that was refreshed
        transactions_added: Number of new transactions (for logging)
        user_id: The user who triggered the refresh

    This function returns immediately. Sync runs in background.
    """
    logger.info(
        f"CORE trigger: item_refreshed org={organization_id} "
        f"item={item_id} added={transactions_added}"
    )
    _run_sync_in_background(
        organization_id=organization_id,
        trigger_source="item_refreshed",
        user_id=user_id,
    )


def on_plaid_item_reconnected(
    organization_id: str,
    item_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> None:
    """
    Trigger CORE sync when a Plaid item is reconnected after error.

    Called after successful re-authentication (LOGIN_REPAIRED webhook
    or manual reconnection).

    Args:
        organization_id: The organization that reconnected the item
        item_id: The Plaid item ID that was reconnected
        user_id: The user who performed the reconnection

    This function returns immediately. Sync runs in background.
    """
    logger.info(
        f"CORE trigger: item_reconnected org={organization_id} item={item_id}"
    )
    _run_sync_in_background(
        organization_id=organization_id,
        trigger_source="item_reconnected",
        user_id=user_id,
    )


def on_plaid_webhook_received(
    organization_id: str,
    item_id: str,
    webhook_type: str,
    webhook_code: str,
) -> None:
    """
    Trigger CORE sync based on Plaid webhook events.

    Only triggers for specific webhook codes that indicate data changes:
    - TRANSACTIONS: SYNC_UPDATES_AVAILABLE, DEFAULT_UPDATE
    - ITEM: LOGIN_REPAIRED

    Args:
        organization_id: The organization that received the webhook
        item_id: The Plaid item ID from the webhook
        webhook_type: Plaid webhook type (TRANSACTIONS, ITEM, etc.)
        webhook_code: Plaid webhook code

    This function returns immediately. Sync runs in background if appropriate.
    """
    # Only trigger for specific events that indicate data changes
    should_sync = False

    if webhook_type == "TRANSACTIONS":
        if webhook_code in ("SYNC_UPDATES_AVAILABLE", "DEFAULT_UPDATE", "INITIAL_UPDATE"):
            should_sync = True
    elif webhook_type == "ITEM":
        if webhook_code == "LOGIN_REPAIRED":
            should_sync = True

    if should_sync:
        logger.info(
            f"CORE trigger: webhook org={organization_id} "
            f"item={item_id} type={webhook_type} code={webhook_code}"
        )
        _run_sync_in_background(
            organization_id=organization_id,
            trigger_source=f"webhook_{webhook_type}_{webhook_code}",
            user_id="system",
        )
    else:
        logger.debug(
            f"CORE webhook ignored: org={organization_id} "
            f"type={webhook_type} code={webhook_code}"
        )


# =============================================================================
# AUTO-RETRY ON STALE DATA
# =============================================================================


def maybe_schedule_auto_retry(
    organization_id: str,
    is_stale: bool,
    sync_status: str,
) -> bool:
    """
    Maybe schedule an auto-retry if data is stale.

    Called from GET /api/core/state when stale data is detected.

    Rules:
    - Only retries if stale=True
    - Only retries if no sync currently running
    - Respects cooldown (max once per hour)
    - Never blocks the response

    Args:
        organization_id: The organization to potentially retry
        is_stale: Whether the data is considered stale
        sync_status: Current sync status from metadata

    Returns:
        True if auto-retry was scheduled, False otherwise
    """
    if not is_stale:
        return False

    if sync_status == 'syncing':
        logger.debug(f"Auto-retry skipped: sync already in progress for org={organization_id}")
        return False

    if _is_sync_running(organization_id):
        logger.debug(f"Auto-retry skipped: sync running for org={organization_id}")
        return False

    if not _can_auto_retry(organization_id):
        logger.debug(f"Auto-retry skipped: cooldown active for org={organization_id}")
        return False

    # Record the attempt and schedule
    _record_retry_attempt(organization_id)

    logger.info(f"CORE auto-retry scheduled for stale data: org={organization_id}")
    _run_sync_in_background(
        organization_id=organization_id,
        trigger_source="auto_retry_stale",
        user_id="system",
    )

    return True


# =============================================================================
# LEGACY COMPATIBILITY (Deprecated - use trigger functions above)
# =============================================================================


def trigger_core_sync_after_exchange(
    organization_id: str,
    user_id: str,
    item_id: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Dict[str, Any]:
    """
    DEPRECATED: Use on_plaid_item_connected() instead.

    This synchronous function is kept for backward compatibility but
    now delegates to the async trigger.
    """
    on_plaid_item_connected(
        organization_id=organization_id,
        item_id=item_id,
        user_id=user_id,
    )
    return {
        'success': True,
        'message': 'CORE sync scheduled in background',
        'async': True,
    }


def trigger_core_sync_after_transaction_sync(
    organization_id: str,
    user_id: str,
    item_id: str,
    transactions_added: int,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Dict[str, Any]:
    """
    DEPRECATED: Use on_plaid_item_refreshed() instead.

    This synchronous function is kept for backward compatibility but
    now delegates to the async trigger.
    """
    on_plaid_item_refreshed(
        organization_id=organization_id,
        item_id=item_id,
        transactions_added=transactions_added,
        user_id=user_id,
    )
    return {
        'success': True,
        'message': 'CORE sync scheduled in background',
        'async': True,
    }


def should_trigger_core_sync(
    operation: str,
    success: bool,
    is_duplicate: bool = False,
) -> bool:
    """
    DEPRECATED: Triggers are now automatic via on_* functions.

    Kept for backward compatibility.
    """
    if not success:
        return False
    if operation == 'exchange':
        return not is_duplicate
    if operation == 'sync':
        return True
    return False
