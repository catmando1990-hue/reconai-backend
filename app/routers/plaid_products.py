# app/routers/plaid_products.py
"""
Plaid Extended Products API - Phase 7.1 Backend Enforcement

Implements additional Plaid product endpoints for:
- Asset Reports (create, get, remove)
- Statements (list, download)
- Identity Match
- Income Verification
- Investments Refresh
- Liabilities
- Transaction Enrichment

CANONICAL LAWS:
- Manual execution only (no cron, triggers, or automation)
- Read-only Plaid data ingestion (no mutations to source data)
- RBAC fail-closed (403 if permission denied)
- Org-isolated (only access data for authenticated organization)
- Full audit logging on all Plaid calls
- Enriched data stored separately (not mixed with source)

============================================================================
ENDPOINTS
============================================================================

Asset Reports:
- POST /api/plaid/assets/report/create     Create asset report
- GET  /api/plaid/assets/report/get        Get asset report
- POST /api/plaid/assets/report/remove     Remove asset report

Statements:
- GET  /api/plaid/statements/list          List available statements
- GET  /api/plaid/statements/download      Download statement PDF

Identity:
- POST /api/plaid/identity/match           Verify identity match

Income:
- GET  /api/plaid/income/get               Get income verification data

Investments:
- POST /api/plaid/investments/refresh      Refresh investment holdings

Liabilities:
- GET  /api/plaid/liabilities/get          Get credit/loan liabilities

Enrichment:
- POST /api/plaid/enrich/transactions      Enrich transactions with metadata

============================================================================
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.auth_context import AuthContext, get_current_context, get_current_organization_id
from app.db import get_db_connection
from app.services.audit_service import record_audit, AuditServiceError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/plaid", tags=["plaid-products"])


# =============================================================================
# REQUEST MODELS
# =============================================================================

class AssetReportCreateRequest(BaseModel):
    """Request to create an asset report."""
    item_id: str = Field(..., description="Plaid item ID")
    days_requested: int = Field(90, ge=1, le=730, description="Days of history (1-730)")
    webhook: Optional[str] = Field(None, description="Webhook URL for report status")


class AssetReportGetRequest(BaseModel):
    """Request to get an asset report."""
    asset_report_token: str = Field(..., description="Asset report token")


class AssetReportRemoveRequest(BaseModel):
    """Request to remove an asset report."""
    asset_report_token: str = Field(..., description="Asset report token to remove")


class StatementsListRequest(BaseModel):
    """Request to list statements."""
    item_id: str = Field(..., description="Plaid item ID")


class StatementsDownloadRequest(BaseModel):
    """Request to download a statement."""
    item_id: str = Field(..., description="Plaid item ID")
    statement_id: str = Field(..., description="Statement ID")


class IdentityMatchRequest(BaseModel):
    """Request to verify identity match."""
    item_id: str = Field(..., description="Plaid item ID")
    legal_name: Optional[str] = Field(None, description="Legal name to match")
    phone_number: Optional[str] = Field(None, description="Phone number to match")
    email_address: Optional[str] = Field(None, description="Email address to match")
    date_of_birth: Optional[str] = Field(None, description="Date of birth (YYYY-MM-DD)")


class IncomeGetRequest(BaseModel):
    """Request to get income verification data."""
    item_id: str = Field(..., description="Plaid item ID")


class InvestmentsRefreshRequest(BaseModel):
    """Request to refresh investment holdings."""
    item_id: str = Field(..., description="Plaid item ID")


class InvestmentsHoldingsGetRequest(BaseModel):
    """Request to get investment holdings."""
    item_id: str = Field(..., description="Plaid item ID")


class InvestmentsTransactionsGetRequest(BaseModel):
    """Request to get investment transactions."""
    item_id: str = Field(..., description="Plaid item ID")
    start_date: str = Field(..., description="Start date (YYYY-MM-DD)")
    end_date: str = Field(..., description="End date (YYYY-MM-DD)")


class LiabilitiesGetRequest(BaseModel):
    """Request to get liabilities."""
    item_id: str = Field(..., description="Plaid item ID")


class EnrichTransactionsRequest(BaseModel):
    """Request to enrich transactions."""
    transactions: List[Dict[str, Any]] = Field(..., description="Transactions to enrich")


# =============================================================================
# RESPONSE HELPERS
# =============================================================================

def validate_request_id(request_id: Optional[str]) -> str:
    """Validate X-Request-ID header. FAIL-CLOSED: Generate if missing."""
    if request_id:
        try:
            UUID(request_id)
            return request_id
        except (ValueError, TypeError):
            pass
    return f"req_{uuid4().hex[:16]}"


def build_response(
    success: bool,
    data: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
    message: Optional[str] = None,
    request_id: str = "",
) -> Dict[str, Any]:
    """Build canonical response envelope."""
    return {
        "status": "ok" if success else "error",
        "data": data or {},
        "error": error,
        "message": message,
        "request_id": request_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def error_response(
    status_code: int,
    error: str,
    message: str,
    request_id: str,
) -> JSONResponse:
    """Build error JSONResponse with canonical envelope."""
    return JSONResponse(
        status_code=status_code,
        content=build_response(
            success=False,
            error=error,
            message=message,
            request_id=request_id,
        ),
        headers={"X-Request-ID": request_id},
    )


def _get_access_token_for_item(organization_id: str, item_id: str) -> Optional[str]:
    """
    Get decrypted access token for a Plaid item.
    ENFORCES ORG ISOLATION: Only returns token if item belongs to org.
    """
    from app.utils.encryption import get_encryption_service

    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT access_token_encrypted
        FROM plaid_items
        WHERE item_id = ? AND organization_id = ? AND status = 'active'
        """,
        (item_id, organization_id)
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    try:
        encryption = get_encryption_service()
        return encryption.decrypt(row["access_token_encrypted"])
    except Exception as e:
        logger.error(f"Failed to decrypt access token for item {item_id}: {e}")
        return None


def _get_plaid_client():
    """Get configured Plaid client."""
    from app.plaid_client import get_plaid_client
    return get_plaid_client()


# =============================================================================
# ASSET REPORTS (Phase 8B - Net Worth Snapshot, Immutable)
# =============================================================================

# Snapshot disclaimer - MUST be included in all asset report responses
ASSET_REPORT_DISCLAIMER = (
    "This snapshot reflects account balances at the time of generation "
    "and is not a live balance."
)

ASSET_REPORT_LABEL = "Historical Asset Snapshot (Plaid)"


@router.post("/assets/report/create", tags=["plaid-products", "assets"])
async def create_asset_report(
    payload: AssetReportCreateRequest,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
) -> JSONResponse:
    """
    Create a Plaid Asset Report (Point-in-Time Net Worth Snapshot).

    MANUAL EXECUTION ONLY - invoked explicitly by authorized users.
    NO AUTO-REGENERATION - each report is a unique snapshot.
    NO BACKGROUND REFRESH - snapshot is immutable once created.
    NO MUTATION - Plaid source data is never modified.

    SNAPSHOT SEMANTICS:
        - Asset reports are IMMUTABLE point-in-time snapshots
        - Once created, contents cannot be changed
        - Suitable for SBA and GovCon underwriting use cases
        - Report reflects balances at generation time, NOT current balances

    Security:
        - Requires authenticated user context (get_current_context)
        - Org-isolated: Only creates report for owned items
        - Audit logged: asset_report_created event
        - Structured error envelope with request_id
    """
    from plaid.model.asset_report_create_request import AssetReportCreateRequest as PlaidAssetReportCreateRequest
    from plaid.model.asset_report_create_request_options import AssetReportCreateRequestOptions

    request_id = validate_request_id(x_request_id)
    organization_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # Get access token (ORG ISOLATION ENFORCED) - check early
    access_token = _get_access_token_for_item(organization_id, payload.item_id)
    if not access_token:
        return error_response(404, "item_not_found", "Plaid item not found or not accessible", request_id)

    # Audit (FAIL-CLOSED) - asset_report_created event
    try:
        record_audit(
            actor=user_id,
            action="asset_report_created",
            entity="plaid_asset_reports",
            entity_id=organization_id,
            payload={
                "item_id": payload.item_id,
                "days_requested": payload.days_requested,
                "organization_id": organization_id,
                "snapshot_type": "net_worth",
            },
            request_id=request_id,
        )
    except AuditServiceError as e:
        logger.error(f"Audit failed for create_asset_report: {e}")
        return error_response(500, "audit_failed", "Audit recording failed", request_id)

    try:
        client = _get_plaid_client()

        request_params = PlaidAssetReportCreateRequest(
            access_tokens=[access_token],
            days_requested=payload.days_requested,
        )

        if payload.webhook:
            request_params.options = AssetReportCreateRequestOptions(
                webhook=payload.webhook
            )

        response = client.asset_report_create(request_params)

        return JSONResponse(
            status_code=200,
            content=build_response(
                success=True,
                data={
                    "asset_report_token": response.asset_report_token,
                    "asset_report_id": response.asset_report_id,
                    "plaid_request_id": response.request_id,
                    "snapshot_type": "net_worth",
                    "label": ASSET_REPORT_LABEL,
                    "disclaimer": ASSET_REPORT_DISCLAIMER,
                },
                message="Asset report snapshot creation initiated. Report will be immutable once generated.",
                request_id=request_id,
            ),
            headers={"X-Request-ID": request_id},
        )

    except Exception as e:
        logger.error(f"Asset report creation failed: {e}")
        return error_response(500, "plaid_error", "Failed to create asset report snapshot", request_id)


def _extract_snapshot_data(report: dict) -> dict:
    """
    Extract and normalize asset report data for snapshot presentation.

    Returns structured data with:
    - report_id
    - generated_at (UTC)
    - institution_summaries
    - account_balances
    - total_assets (simple sum of current balances)

    NO inferred values. NO projections. NO "current balance" language.
    """
    report_id = report.get("asset_report_id")
    generated_at = report.get("date_generated")  # UTC timestamp from Plaid

    # Extract institution summaries
    institution_summaries = []
    account_balances = []
    total_assets = 0.0

    items = report.get("items", [])
    for item in items:
        institution = item.get("institution_name", "Unknown Institution")
        institution_id = item.get("institution_id")

        institution_summary = {
            "institution_name": institution,
            "institution_id": institution_id,
            "accounts_count": 0,
            "total_balance": 0.0,
        }

        accounts = item.get("accounts", [])
        for account in accounts:
            account_id = account.get("account_id")
            account_name = account.get("name", "Unknown Account")
            account_type = account.get("type")
            account_subtype = account.get("subtype")

            # Get balance snapshot - use historical_balances if available, else balances
            balances = account.get("balances", {})
            balance_current = balances.get("current") or 0.0

            # For historical accuracy, check historical_balances array
            historical = account.get("historical_balances", [])
            if historical and len(historical) > 0:
                # Use most recent historical balance (first in array)
                balance_current = historical[0].get("current") or balance_current

            account_balances.append({
                "account_id": account_id,
                "account_name": account_name,
                "account_type": account_type,
                "account_subtype": account_subtype,
                "balance_at_snapshot": balance_current,
                "institution_name": institution,
            })

            institution_summary["accounts_count"] += 1
            institution_summary["total_balance"] += balance_current
            total_assets += balance_current

        institution_summaries.append(institution_summary)

    return {
        "report_id": report_id,
        "generated_at": generated_at,
        "institution_summaries": institution_summaries,
        "account_balances": account_balances,
        "total_assets": round(total_assets, 2),
    }


@router.post("/assets/report/get", tags=["plaid-products", "assets"])
async def get_asset_report(
    payload: AssetReportGetRequest,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
) -> JSONResponse:
    """
    Get a completed Plaid Asset Report (Immutable Net Worth Snapshot).

    MANUAL EXECUTION ONLY - invoked explicitly by authorized users.
    NO REGENERATION - returns the exact snapshot as generated.
    NO BACKGROUND REFRESH - data is immutable.
    NO MUTATION - Plaid source data is never modified.

    SNAPSHOT SEMANTICS:
        - Returns IMMUTABLE point-in-time snapshot
        - Contents reflect balances at generation time
        - generated_at timestamp is preserved and surfaced
        - total_assets is a simple sum (NO inferred values, NO projections)

    Response includes:
        - report_id: Unique identifier for this snapshot
        - generated_at: UTC timestamp when snapshot was created
        - institution_summaries: Summary per financial institution
        - account_balances: Balance per account at snapshot time
        - total_assets: Simple sum of all account balances
        - label: "Historical Asset Snapshot (Plaid)"
        - disclaimer: Immutability and point-in-time notice

    Security:
        - Requires authenticated user context (get_current_context)
        - Audit logged: asset_report_viewed event
        - Structured error envelope with request_id
    """
    from plaid.model.asset_report_get_request import AssetReportGetRequest as PlaidAssetReportGetRequest

    request_id = validate_request_id(x_request_id)
    organization_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # Audit (FAIL-CLOSED) - asset_report_viewed event
    try:
        record_audit(
            actor=user_id,
            action="asset_report_viewed",
            entity="plaid_asset_reports",
            entity_id=organization_id,
            payload={
                "asset_report_token": payload.asset_report_token[:20] + "...",  # Truncate for security
                "organization_id": organization_id,
            },
            request_id=request_id,
        )
    except AuditServiceError as e:
        logger.error(f"Audit failed for get_asset_report: {e}")
        return error_response(500, "audit_failed", "Audit recording failed", request_id)

    try:
        client = _get_plaid_client()

        request_params = PlaidAssetReportGetRequest(
            asset_report_token=payload.asset_report_token,
        )

        response = client.asset_report_get(request_params)

        # Convert to dict for processing
        report_data = response.to_dict() if hasattr(response, 'to_dict') else {}
        report = report_data.get("report", {})

        # Extract and normalize snapshot data
        snapshot = _extract_snapshot_data(report)

        # Build frontend-compatible accounts with balances: { available, current }
        report_accounts = []
        for ab in snapshot.get("account_balances", []):
            report_accounts.append({
                "account_id": ab.get("account_id"),
                "name": ab.get("account_name"),
                "type": ab.get("account_type"),
                "subtype": ab.get("account_subtype"),
                "institution_name": ab.get("institution_name"),
                "balances": {
                    "available": ab.get("balance_at_snapshot"),
                    "current": ab.get("balance_at_snapshot"),
                },
            })

        # Build report object for frontend contract
        report_obj = {
            "report_id": snapshot["report_id"],
            "generated_at": snapshot["generated_at"],
            "total_assets": snapshot["total_assets"],
            "accounts": report_accounts,
            "institution_summaries": snapshot["institution_summaries"],
        }

        return JSONResponse(
            status_code=200,
            content=build_response(
                success=True,
                data={
                    # Snapshot metadata
                    "label": ASSET_REPORT_LABEL,
                    "disclaimer": ASSET_REPORT_DISCLAIMER,
                    "snapshot_type": "net_worth",

                    # Frontend contract: report object with accounts
                    "report": report_obj,

                    # Core snapshot data (kept for backward compatibility)
                    "report_id": snapshot["report_id"],
                    "generated_at": snapshot["generated_at"],
                    "total_assets": snapshot["total_assets"],

                    # Detailed breakdowns
                    "institution_summaries": snapshot["institution_summaries"],
                    "account_balances": snapshot["account_balances"],

                    # Warnings from Plaid (if any)
                    "warnings": report_data.get("warnings", []),

                    # Full raw report for compliance (optional use)
                    "raw_report": report,
                },
                message="Historical asset snapshot retrieved. Data reflects balances at generation time.",
                request_id=request_id,
            ),
            headers={"X-Request-ID": request_id},
        )

    except Exception as e:
        logger.error(f"Asset report get failed: {e}")
        error_msg = str(e)
        if "PRODUCT_NOT_READY" in error_msg:
            return error_response(
                202,
                "report_pending",
                "Asset report snapshot is still being generated by Plaid. Retry later.",
                request_id,
            )
        return error_response(500, "plaid_error", "Failed to retrieve asset report snapshot", request_id)


@router.post("/assets/report/remove", tags=["plaid-products", "assets"])
async def remove_asset_report(
    payload: AssetReportRemoveRequest,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
) -> JSONResponse:
    """
    Remove a Plaid Asset Report snapshot.

    MANUAL EXECUTION ONLY - invoked explicitly by authorized users.
    NO AUTOMATION - removal must be explicitly requested.

    IMPORTANT:
        - This permanently removes the snapshot from Plaid
        - The snapshot cannot be recovered after removal
        - Consider audit/compliance requirements before removal

    Security:
        - Requires authenticated user context (get_current_context)
        - Audit logged: asset_report_removed event
        - Structured error envelope with request_id
    """
    from plaid.model.asset_report_remove_request import AssetReportRemoveRequest as PlaidAssetReportRemoveRequest

    request_id = validate_request_id(x_request_id)
    organization_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # Audit (FAIL-CLOSED) - asset_report_removed event
    try:
        record_audit(
            actor=user_id,
            action="asset_report_removed",
            entity="plaid_asset_reports",
            entity_id=organization_id,
            payload={
                "asset_report_token": payload.asset_report_token[:20] + "...",  # Truncate for security
                "organization_id": organization_id,
                "removal_reason": "user_requested",
            },
            request_id=request_id,
        )
    except AuditServiceError as e:
        logger.error(f"Audit failed for remove_asset_report: {e}")
        return error_response(500, "audit_failed", "Audit recording failed", request_id)

    try:
        client = _get_plaid_client()

        request_params = PlaidAssetReportRemoveRequest(
            asset_report_token=payload.asset_report_token,
        )

        response = client.asset_report_remove(request_params)

        logger.info(f"Asset report snapshot removed: token={payload.asset_report_token[:20]}..., user={user_id}")

        return JSONResponse(
            status_code=200,
            content=build_response(
                success=True,
                data={
                    "removed": response.removed,
                    "label": ASSET_REPORT_LABEL,
                    "message": "Snapshot permanently removed from Plaid",
                },
                message="Asset report snapshot removed successfully",
                request_id=request_id,
            ),
            headers={"X-Request-ID": request_id},
        )

    except Exception as e:
        logger.error(f"Asset report remove failed: {e}")
        return error_response(500, "plaid_error", "Failed to remove asset report snapshot", request_id)


# =============================================================================
# STATEMENTS (Phase 8A - Evidence-Grade Hardened)
# =============================================================================

def _compute_period_dates(year: int, month: int) -> tuple:
    """
    Compute period_start and period_end dates from year and month.

    Returns:
        Tuple of (period_start, period_end) as ISO date strings
    """
    import calendar

    # First day of the month
    period_start = f"{year:04d}-{month:02d}-01"

    # Last day of the month
    last_day = calendar.monthrange(year, month)[1]
    period_end = f"{year:04d}-{month:02d}-{last_day:02d}"

    return period_start, period_end


@router.get("/statements/list", tags=["plaid-products", "statements"])
async def list_statements(
    item_id: str,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
) -> JSONResponse:
    """
    List available bank statements for a Plaid item.

    MANUAL EXECUTION ONLY - invoked explicitly by authorized users.
    NO CACHING - fresh data on every request.
    NO BACKGROUND FETCH - synchronous Plaid API call only.
    NO MUTATION - read-only operation.

    Security:
        - Requires authenticated user context (get_current_context)
        - Org-isolated: Only lists statements for owned items
        - Audit logged: statement_list_viewed event
        - Structured error envelope with request_id

    Response includes period_start and period_end for each statement
    (derived from month/year) for audit evidence requirements.
    """
    from plaid.model.statements_list_request import StatementsListRequest as PlaidStatementsListRequest

    request_id = validate_request_id(x_request_id)
    organization_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # Audit (FAIL-CLOSED) - statement_list_viewed event
    try:
        record_audit(
            actor=user_id,
            action="statement_list_viewed",
            entity="plaid_statements",
            entity_id=organization_id,
            payload={
                "item_id": item_id,
                "organization_id": organization_id,
            },
            request_id=request_id,
        )
    except AuditServiceError as e:
        logger.error(f"Audit failed for list_statements: {e}")
        return error_response(500, "audit_failed", "Audit recording failed", request_id)

    # Get access token (ORG ISOLATION ENFORCED)
    access_token = _get_access_token_for_item(organization_id, item_id)
    if not access_token:
        return error_response(404, "item_not_found", "Plaid item not found or not accessible", request_id)

    try:
        client = _get_plaid_client()

        request_params = PlaidStatementsListRequest(
            access_token=access_token,
        )

        response = client.statements_list(request_params)

        # Convert statements to serializable format with period dates
        statements = []
        if hasattr(response, 'accounts'):
            for account in response.accounts:
                if hasattr(account, 'statements'):
                    for stmt in account.statements:
                        month = stmt.month if hasattr(stmt, 'month') else None
                        year = stmt.year if hasattr(stmt, 'year') else None

                        # Compute period dates for audit evidence
                        period_start = None
                        period_end = None
                        if month and year:
                            period_start, period_end = _compute_period_dates(year, month)

                        statements.append({
                            "statement_id": stmt.statement_id if hasattr(stmt, 'statement_id') else None,
                            "account_id": account.account_id if hasattr(account, 'account_id') else None,
                            "month": month,
                            "year": year,
                            "period_start": period_start,
                            "period_end": period_end,
                        })

        return JSONResponse(
            status_code=200,
            content=build_response(
                success=True,
                data={
                    "statements": statements,
                    "total": len(statements),
                    "item_id": item_id,
                },
                message="Statements listed",
                request_id=request_id,
            ),
            headers={"X-Request-ID": request_id},
        )

    except Exception as e:
        logger.error(f"Statements list failed: {e}")
        return error_response(500, "plaid_error", "Failed to list statements", request_id)


def _sanitize_filename(name: str) -> str:
    """
    Sanitize a filename to be ZIP-safe and deterministic.

    Removes/replaces characters that could cause issues in ZIP archives
    or filesystem operations.
    """
    import re
    # Replace any non-alphanumeric except dash, underscore, dot with underscore
    sanitized = re.sub(r'[^a-zA-Z0-9\-_.]', '_', name)
    # Collapse multiple underscores
    sanitized = re.sub(r'_+', '_', sanitized)
    # Remove leading/trailing underscores
    sanitized = sanitized.strip('_')
    return sanitized or "statement"


def _compute_sha256(data: bytes) -> str:
    """
    Compute SHA-256 hash of binary data.

    Returns:
        Lowercase hex string of the hash
    """
    import hashlib
    return hashlib.sha256(data).hexdigest()


@router.get("/statements/download", tags=["plaid-products", "statements"])
async def download_statement(
    item_id: str,
    statement_id: str,
    account_id: Optional[str] = None,
    request: Request = None,
    ctx: AuthContext = Depends(get_current_context),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
) -> StreamingResponse:
    """
    Download a bank statement PDF with evidence-grade metadata.

    MANUAL EXECUTION ONLY - invoked explicitly by authorized users.
    NO CACHING - fresh download on every request.
    NO BACKGROUND FETCH - synchronous Plaid API call only.
    NO MUTATION - read-only operation, file NOT persisted unless stored by policy.

    Security:
        - Requires authenticated user context (get_current_context)
        - Org-isolated: Only downloads statements for owned items
        - Audit logged: statement_downloaded event
        - Structured error envelope with request_id

    Evidence Requirements:
        - SHA-256 hash computed on PDF bytes and returned in X-SHA256-Hash header
        - Deterministic, ZIP-safe filename
        - Full metadata in response headers

    Response Headers:
        - X-Statement-ID: The statement identifier
        - X-Account-ID: The account identifier (if available)
        - X-Period-Start: Start date of statement period (YYYY-MM-DD)
        - X-Period-End: End date of statement period (YYYY-MM-DD)
        - X-SHA256-Hash: SHA-256 hash of PDF bytes (lowercase hex)
        - X-Request-ID: Request trace identifier
        - Content-Disposition: Deterministic filename

    Query Parameters:
        - item_id: Plaid item ID (required)
        - statement_id: Statement ID from /statements/list (required)
        - account_id: Account ID for metadata (optional, fetched if not provided)
    """
    from plaid.model.statements_download_request import StatementsDownloadRequest as PlaidStatementsDownloadRequest
    from plaid.model.statements_list_request import StatementsListRequest as PlaidStatementsListRequest
    import io

    request_id = validate_request_id(x_request_id)
    organization_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # Get access token (ORG ISOLATION ENFORCED) - check early before audit
    access_token = _get_access_token_for_item(organization_id, item_id)
    if not access_token:
        return error_response(404, "item_not_found", "Plaid item not found or not accessible", request_id)

    # Fetch statement metadata for evidence completeness
    period_start = None
    period_end = None
    resolved_account_id = account_id

    try:
        client = _get_plaid_client()

        # Get statement metadata from list endpoint
        list_params = PlaidStatementsListRequest(access_token=access_token)
        list_response = client.statements_list(list_params)

        # Find the specific statement to get metadata
        if hasattr(list_response, 'accounts'):
            for account in list_response.accounts:
                if hasattr(account, 'statements'):
                    for stmt in account.statements:
                        if hasattr(stmt, 'statement_id') and stmt.statement_id == statement_id:
                            resolved_account_id = account.account_id if hasattr(account, 'account_id') else account_id
                            month = stmt.month if hasattr(stmt, 'month') else None
                            year = stmt.year if hasattr(stmt, 'year') else None
                            if month and year:
                                period_start, period_end = _compute_period_dates(year, month)
                            break
                if period_start:
                    break

    except Exception as e:
        logger.warning(f"Could not fetch statement metadata for {statement_id}: {e}")
        # Continue with download even if metadata fetch fails

    # Audit (FAIL-CLOSED) - statement_downloaded event with full metadata
    try:
        record_audit(
            actor=user_id,
            action="statement_downloaded",
            entity="plaid_statements",
            entity_id=statement_id,
            payload={
                "item_id": item_id,
                "statement_id": statement_id,
                "account_id": resolved_account_id,
                "organization_id": organization_id,
                "period_start": period_start,
                "period_end": period_end,
            },
            request_id=request_id,
        )
    except AuditServiceError as e:
        logger.error(f"Audit failed for download_statement: {e}")
        return error_response(500, "audit_failed", "Audit recording failed", request_id)

    try:
        # Download the statement PDF
        download_params = PlaidStatementsDownloadRequest(
            access_token=access_token,
            statement_id=statement_id,
        )

        response = client.statements_download(download_params)

        # Read PDF bytes
        pdf_content = response.read() if hasattr(response, 'read') else response

        # Compute SHA-256 hash for evidence integrity
        sha256_hash = _compute_sha256(pdf_content)

        # Build deterministic, ZIP-safe filename
        filename_parts = ["statement", statement_id]
        if period_start:
            filename_parts.append(period_start)
        filename = _sanitize_filename("-".join(filename_parts)) + ".pdf"

        # Build response headers with full evidence metadata
        response_headers = {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Request-ID": request_id,
            "X-Statement-ID": statement_id,
            "X-SHA256-Hash": sha256_hash,
        }

        # Add optional metadata headers if available
        if resolved_account_id:
            response_headers["X-Account-ID"] = resolved_account_id
        if period_start:
            response_headers["X-Period-Start"] = period_start
        if period_end:
            response_headers["X-Period-End"] = period_end

        logger.info(
            f"Statement downloaded: statement_id={statement_id}, "
            f"sha256={sha256_hash[:16]}..., size={len(pdf_content)} bytes"
        )

        return StreamingResponse(
            io.BytesIO(pdf_content),
            media_type="application/pdf",
            headers=response_headers,
        )

    except Exception as e:
        logger.error(f"Statement download failed: {e}")
        return error_response(500, "plaid_error", "Failed to download statement", request_id)


# =============================================================================
# IDENTITY MATCH
# =============================================================================

@router.post("/identity/match", tags=["plaid-products", "identity"])
async def identity_match(
    payload: IdentityMatchRequest,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
) -> JSONResponse:
    """
    Verify identity information matches bank records.

    MANUAL EXECUTION ONLY - invoked explicitly by authorized users.

    Compares provided identity data against what the bank has on file.

    Security:
        - Requires authenticated user context
        - Org-isolated: Only matches identity for owned items
        - Audit logged (PII redacted in logs)
    """
    from plaid.model.identity_match_request import IdentityMatchRequest as PlaidIdentityMatchRequest
    from plaid.model.identity_match_user import IdentityMatchUser

    request_id = validate_request_id(x_request_id)
    organization_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # Audit (FAIL-CLOSED) - PII redacted
    try:
        record_audit(
            actor=user_id,
            action="plaid.identity.match",
            entity="plaid",
            entity_id=organization_id,
            payload={
                "item_id": payload.item_id,
                "has_legal_name": bool(payload.legal_name),
                "has_phone": bool(payload.phone_number),
                "has_email": bool(payload.email_address),
                "has_dob": bool(payload.date_of_birth),
            },
            request_id=request_id,
        )
    except AuditServiceError as e:
        logger.error(f"Audit failed for identity_match: {e}")
        return error_response(500, "audit_failed", "Audit recording failed", request_id)

    # Get access token (ORG ISOLATION ENFORCED)
    access_token = _get_access_token_for_item(organization_id, payload.item_id)
    if not access_token:
        return error_response(404, "item_not_found", "Plaid item not found or not accessible", request_id)

    try:
        client = _get_plaid_client()

        # Build user data for matching
        user_data = {}
        if payload.legal_name:
            user_data["legal_name"] = payload.legal_name
        if payload.phone_number:
            user_data["phone_number"] = payload.phone_number
        if payload.email_address:
            user_data["email_address"] = payload.email_address
        if payload.date_of_birth:
            user_data["date_of_birth"] = payload.date_of_birth

        request_params = PlaidIdentityMatchRequest(
            access_token=access_token,
            user=IdentityMatchUser(**user_data) if user_data else None,
        )

        response = client.identity_match(request_params)

        # Extract match scores
        accounts_data = []
        if hasattr(response, 'accounts'):
            for account in response.accounts:
                account_data = {
                    "account_id": account.account_id if hasattr(account, 'account_id') else None,
                }
                if hasattr(account, 'legal_name'):
                    account_data["legal_name_score"] = account.legal_name.score if hasattr(account.legal_name, 'score') else None
                if hasattr(account, 'phone_number'):
                    account_data["phone_score"] = account.phone_number.score if hasattr(account.phone_number, 'score') else None
                if hasattr(account, 'email_address'):
                    account_data["email_score"] = account.email_address.score if hasattr(account.email_address, 'score') else None
                if hasattr(account, 'date_of_birth'):
                    account_data["dob_score"] = account.date_of_birth.score if hasattr(account.date_of_birth, 'score') else None
                accounts_data.append(account_data)

        return JSONResponse(
            status_code=200,
            content=build_response(
                success=True,
                data={
                    "accounts": accounts_data,
                },
                message="Identity match completed",
                request_id=request_id,
            ),
            headers={"X-Request-ID": request_id},
        )

    except Exception as e:
        logger.error(f"Identity match failed: {e}")
        return error_response(500, "plaid_error", "Failed to verify identity match", request_id)


# =============================================================================
# INCOME
# =============================================================================

@router.get("/income/get", tags=["plaid-products", "income"])
async def get_income(
    item_id: str,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
) -> JSONResponse:
    """
    Get income verification data from Plaid.

    MANUAL EXECUTION ONLY - invoked explicitly by authorized users.

    Security:
        - Requires authenticated user context
        - Org-isolated: Only gets income for owned items
        - Audit logged
    """
    from plaid.model.income_verification_paystubs_get_request import IncomeVerificationPaystubsGetRequest

    request_id = validate_request_id(x_request_id)
    organization_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # Audit (FAIL-CLOSED)
    try:
        record_audit(
            actor=user_id,
            action="plaid.income.get",
            entity="plaid",
            entity_id=organization_id,
            payload={"item_id": item_id},
            request_id=request_id,
        )
    except AuditServiceError as e:
        logger.error(f"Audit failed for get_income: {e}")
        return error_response(500, "audit_failed", "Audit recording failed", request_id)

    # Get access token (ORG ISOLATION ENFORCED)
    access_token = _get_access_token_for_item(organization_id, item_id)
    if not access_token:
        return error_response(404, "item_not_found", "Plaid item not found or not accessible", request_id)

    try:
        client = _get_plaid_client()

        # Try to get income data via paystubs
        request_params = IncomeVerificationPaystubsGetRequest(
            access_token=access_token,
        )

        response = client.income_verification_paystubs_get(request_params)

        # Convert to serializable format
        paystubs = []
        if hasattr(response, 'paystubs'):
            for paystub in response.paystubs:
                paystubs.append(paystub.to_dict() if hasattr(paystub, 'to_dict') else {})

        return JSONResponse(
            status_code=200,
            content=build_response(
                success=True,
                data={
                    "paystubs": paystubs,
                    "total": len(paystubs),
                },
                message="Income data retrieved",
                request_id=request_id,
            ),
            headers={"X-Request-ID": request_id},
        )

    except Exception as e:
        logger.error(f"Income get failed: {e}")
        error_msg = str(e)
        if "PRODUCT_NOT_ENABLED" in error_msg or "INVALID_PRODUCT" in error_msg:
            return error_response(400, "product_not_enabled", "Income product not enabled for this item", request_id)
        return error_response(500, "plaid_error", "Failed to get income data", request_id)


# =============================================================================
# INVESTMENTS (Phase 8C - Read-Only Financial Position Data)
# =============================================================================

@router.post("/investments/refresh", tags=["plaid-products", "investments"])
async def refresh_investments(
    payload: InvestmentsRefreshRequest,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
) -> JSONResponse:
    """
    Refresh investment holdings from Plaid (Manual Trigger Only).

    MANUAL EXECUTION ONLY - invoked explicitly by authorized users.
    NO BACKGROUND REFRESH - this is an explicit user-triggered action.
    NO AUTOMATION - must be manually invoked.

    Returns:
        - refresh_status: Status of the refresh request
        - refreshed_at: UTC timestamp of refresh initiation

    Security:
        - Requires authenticated user context (get_current_context)
        - Org-isolated: Only refreshes investments for owned items
        - Audit logged: investments_refreshed event
        - Structured error envelope with request_id
    """
    from plaid.model.investments_refresh_request import InvestmentsRefreshRequest as PlaidInvestmentsRefreshRequest

    request_id = validate_request_id(x_request_id)
    organization_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # Get access token (ORG ISOLATION ENFORCED) - check early
    access_token = _get_access_token_for_item(organization_id, payload.item_id)
    if not access_token:
        return error_response(404, "item_not_found", "Plaid item not found or not accessible", request_id)

    # Audit (FAIL-CLOSED) - investments_refreshed event
    try:
        record_audit(
            actor=user_id,
            action="investments_refreshed",
            entity="plaid_investments",
            entity_id=organization_id,
            payload={
                "item_id": payload.item_id,
                "organization_id": organization_id,
                "trigger": "manual",
            },
            request_id=request_id,
        )
    except AuditServiceError as e:
        logger.error(f"Audit failed for refresh_investments: {e}")
        return error_response(500, "audit_failed", "Audit recording failed", request_id)

    try:
        client = _get_plaid_client()

        request_params = PlaidInvestmentsRefreshRequest(
            access_token=access_token,
        )

        response = client.investments_refresh(request_params)
        refreshed_at = datetime.now(timezone.utc).isoformat()

        return JSONResponse(
            status_code=200,
            content=build_response(
                success=True,
                data={
                    "refresh_status": "initiated",
                    "refreshed_at": refreshed_at,
                    "plaid_request_id": response.request_id if hasattr(response, 'request_id') else None,
                    "item_id": payload.item_id,
                },
                message="Investment holdings refresh initiated. Holdings will be updated on next retrieval.",
                request_id=request_id,
            ),
            headers={"X-Request-ID": request_id},
        )

    except Exception as e:
        logger.error(f"Investments refresh failed: {e}")
        error_msg = str(e)
        if "PRODUCT_NOT_ENABLED" in error_msg or "INVALID_PRODUCT" in error_msg:
            return error_response(400, "product_not_enabled", "Investments product not enabled for this item", request_id)
        return error_response(500, "plaid_error", "Failed to refresh investments", request_id)


@router.post("/investments/holdings/get", tags=["plaid-products", "investments"])
async def get_investment_holdings(
    payload: InvestmentsHoldingsGetRequest,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
) -> JSONResponse:
    """
    Get investment holdings from Plaid (Read-Only Financial Position).

    MANUAL EXECUTION ONLY - invoked explicitly by authorized users.
    NO BACKGROUND REFRESH - synchronous Plaid API call only.
    NO MUTATION - read-only operation.

    OUTPUT RULES:
        - Each holding includes: institution, account, security_name,
          quantity, value, as_of timestamp
        - NO inferred performance metrics
        - NO projections

    LANGUAGE:
        - Uses "value as of" (not "current value")
        - Uses "reported quantity" (not "real-time holdings")

    Security:
        - Requires authenticated user context (get_current_context)
        - Org-isolated: Only gets holdings for owned items
        - Audit logged: investments_holdings_viewed event
        - Structured error envelope with request_id
    """
    from plaid.model.investments_holdings_get_request import InvestmentsHoldingsGetRequest as PlaidInvestmentsHoldingsGetRequest

    request_id = validate_request_id(x_request_id)
    organization_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # Get access token (ORG ISOLATION ENFORCED) - check early
    access_token = _get_access_token_for_item(organization_id, payload.item_id)
    if not access_token:
        return error_response(404, "item_not_found", "Plaid item not found or not accessible", request_id)

    # Audit (FAIL-CLOSED) - investments_holdings_viewed event
    try:
        record_audit(
            actor=user_id,
            action="investments_holdings_viewed",
            entity="plaid_investments",
            entity_id=organization_id,
            payload={
                "item_id": payload.item_id,
                "organization_id": organization_id,
            },
            request_id=request_id,
        )
    except AuditServiceError as e:
        logger.error(f"Audit failed for get_investment_holdings: {e}")
        return error_response(500, "audit_failed", "Audit recording failed", request_id)

    try:
        client = _get_plaid_client()

        request_params = PlaidInvestmentsHoldingsGetRequest(
            access_token=access_token,
        )

        response = client.investments_holdings_get(request_params)

        # Build account and security lookup maps
        account_map = {}
        accounts_list = []
        if hasattr(response, 'accounts'):
            for acc in (response.accounts or []):
                acc_dict = acc.to_dict() if hasattr(acc, 'to_dict') else {}
                account_map[acc_dict.get("account_id")] = acc_dict
                balances = acc_dict.get("balances", {})
                accounts_list.append({
                    "account_id": acc_dict.get("account_id"),
                    "name": acc_dict.get("name"),
                    "official_name": acc_dict.get("official_name"),
                    "type": acc_dict.get("type"),
                    "subtype": acc_dict.get("subtype"),
                    "mask": acc_dict.get("mask"),
                    "balances": {
                        "available": balances.get("available"),
                        "current": balances.get("current"),
                    },
                })

        security_map = {}
        securities_list = []
        if hasattr(response, 'securities'):
            for sec in (response.securities or []):
                sec_dict = sec.to_dict() if hasattr(sec, 'to_dict') else {}
                security_map[sec_dict.get("security_id")] = sec_dict
                securities_list.append({
                    "security_id": sec_dict.get("security_id"),
                    "name": sec_dict.get("name"),
                    "ticker_symbol": sec_dict.get("ticker_symbol"),
                    "type": sec_dict.get("type"),
                    "close_price": sec_dict.get("close_price"),
                    "close_price_as_of": sec_dict.get("close_price_as_of"),
                    "iso_currency_code": sec_dict.get("iso_currency_code"),
                })

        # Normalize holdings with frontend-expected field names
        holdings = []
        total_value = 0.0

        if hasattr(response, 'holdings'):
            for holding in (response.holdings or []):
                h_dict = holding.to_dict() if hasattr(holding, 'to_dict') else {}

                account_id = h_dict.get("account_id")
                security_id = h_dict.get("security_id")
                account_info = account_map.get(account_id, {})
                security_info = security_map.get(security_id, {})

                quantity = h_dict.get("quantity", 0)
                institution_price = h_dict.get("institution_price")
                institution_value = h_dict.get("institution_value") or (quantity * (institution_price or 0))

                holdings.append({
                    "account_id": account_id,
                    "security_id": security_id,
                    "institution": account_info.get("official_name") or account_info.get("name", "Unknown Institution"),
                    "account_name": account_info.get("name", "Unknown Account"),
                    "account_mask": account_info.get("mask"),
                    "security_name": security_info.get("name", "Unknown Security"),
                    "security_ticker": security_info.get("ticker_symbol"),
                    "security_type": security_info.get("type"),
                    "quantity": quantity,
                    "institution_price": institution_price,
                    "institution_value": institution_value,
                    "institution_price_as_of": h_dict.get("institution_price_as_of_date"),
                    "cost_basis": h_dict.get("cost_basis"),
                    "iso_currency_code": h_dict.get("iso_currency_code"),
                })

                total_value += institution_value or 0

        return JSONResponse(
            status_code=200,
            content=build_response(
                success=True,
                data={
                    "holdings": holdings,
                    "securities": securities_list,
                    "accounts": accounts_list,
                    "total_holdings_value": round(total_value, 2),
                    "holdings_count": len(holdings),
                    "item_id": payload.item_id,
                    "data_retrieved_at": datetime.now(timezone.utc).isoformat(),
                },
                message="Investment holdings retrieved. Values reported as of timestamps shown.",
                request_id=request_id,
            ),
            headers={"X-Request-ID": request_id},
        )

    except Exception as e:
        logger.error(f"Investments holdings get failed: {e}")
        error_msg = str(e)
        if "PRODUCT_NOT_ENABLED" in error_msg or "INVALID_PRODUCT" in error_msg:
            return error_response(400, "product_not_enabled", "Investments product not enabled for this item", request_id)
        return error_response(500, "plaid_error", "Failed to get investment holdings", request_id)


@router.post("/investments/transactions/get", tags=["plaid-products", "investments"])
async def get_investment_transactions(
    payload: InvestmentsTransactionsGetRequest,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
) -> JSONResponse:
    """
    Get investment transactions from Plaid (Read-Only, Date-Bounded).

    MANUAL EXECUTION ONLY - invoked explicitly by authorized users.
    NO BACKGROUND REFRESH - synchronous Plaid API call only.
    NO MUTATION - read-only operation.

    OUTPUT RULES:
        - Read-only transaction data
        - Date-bounded (start_date to end_date)
        - NO inferred performance metrics
        - NO gain/loss calculations beyond raw data

    Security:
        - Requires authenticated user context (get_current_context)
        - Org-isolated: Only gets transactions for owned items
        - Audit logged: investments_transactions_viewed event
        - Structured error envelope with request_id
    """
    from plaid.model.investments_transactions_get_request import InvestmentsTransactionsGetRequest as PlaidInvestmentsTransactionsGetRequest
    from plaid.model.investments_transactions_get_request_options import InvestmentsTransactionsGetRequestOptions
    from datetime import date as date_type

    request_id = validate_request_id(x_request_id)
    organization_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # Validate date format
    try:
        start_date = date_type.fromisoformat(payload.start_date)
        end_date = date_type.fromisoformat(payload.end_date)
    except ValueError:
        return error_response(400, "invalid_date", "Dates must be in YYYY-MM-DD format", request_id)

    if start_date > end_date:
        return error_response(400, "invalid_date_range", "start_date must be before or equal to end_date", request_id)

    # Get access token (ORG ISOLATION ENFORCED) - check early
    access_token = _get_access_token_for_item(organization_id, payload.item_id)
    if not access_token:
        return error_response(404, "item_not_found", "Plaid item not found or not accessible", request_id)

    # Audit (FAIL-CLOSED) - investments_transactions_viewed event
    try:
        record_audit(
            actor=user_id,
            action="investments_transactions_viewed",
            entity="plaid_investments",
            entity_id=organization_id,
            payload={
                "item_id": payload.item_id,
                "organization_id": organization_id,
                "start_date": payload.start_date,
                "end_date": payload.end_date,
            },
            request_id=request_id,
        )
    except AuditServiceError as e:
        logger.error(f"Audit failed for get_investment_transactions: {e}")
        return error_response(500, "audit_failed", "Audit recording failed", request_id)

    try:
        client = _get_plaid_client()

        request_params = PlaidInvestmentsTransactionsGetRequest(
            access_token=access_token,
            start_date=start_date,
            end_date=end_date,
        )

        response = client.investments_transactions_get(request_params)

        # Build account and security lookup maps
        account_map = {}
        if hasattr(response, 'accounts'):
            for acc in (response.accounts or []):
                acc_dict = acc.to_dict() if hasattr(acc, 'to_dict') else {}
                account_map[acc_dict.get("account_id")] = acc_dict

        security_map = {}
        if hasattr(response, 'securities'):
            for sec in (response.securities or []):
                sec_dict = sec.to_dict() if hasattr(sec, 'to_dict') else {}
                security_map[sec_dict.get("security_id")] = sec_dict

        # Normalize transactions (read-only, no performance metrics)
        transactions = []
        if hasattr(response, 'investment_transactions'):
            for tx in (response.investment_transactions or []):
                tx_dict = tx.to_dict() if hasattr(tx, 'to_dict') else {}

                account_id = tx_dict.get("account_id")
                security_id = tx_dict.get("security_id")
                account_info = account_map.get(account_id, {})
                security_info = security_map.get(security_id, {})

                transactions.append({
                    "transaction_id": tx_dict.get("investment_transaction_id"),
                    "account_id": account_id,
                    "account_name": account_info.get("name", "Unknown Account"),
                    "security_id": security_id,
                    "security_name": security_info.get("name", "Unknown Security"),
                    "security_ticker": security_info.get("ticker_symbol"),
                    "date": tx_dict.get("date"),
                    "type": tx_dict.get("type"),
                    "subtype": tx_dict.get("subtype"),
                    "quantity": tx_dict.get("quantity"),
                    "price": tx_dict.get("price"),
                    "amount": tx_dict.get("amount"),
                    "fees": tx_dict.get("fees"),
                    "name": tx_dict.get("name"),
                })

        return JSONResponse(
            status_code=200,
            content=build_response(
                success=True,
                data={
                    "transactions": transactions,
                    "transactions_count": len(transactions),
                    "date_range": {
                        "start_date": payload.start_date,
                        "end_date": payload.end_date,
                    },
                    "item_id": payload.item_id,
                    "data_retrieved_at": datetime.now(timezone.utc).isoformat(),
                },
                message="Investment transactions retrieved for specified date range.",
                request_id=request_id,
            ),
            headers={"X-Request-ID": request_id},
        )

    except Exception as e:
        logger.error(f"Investments transactions get failed: {e}")
        error_msg = str(e)
        if "PRODUCT_NOT_ENABLED" in error_msg or "INVALID_PRODUCT" in error_msg:
            return error_response(400, "product_not_enabled", "Investments product not enabled for this item", request_id)
        return error_response(500, "plaid_error", "Failed to get investment transactions", request_id)


# =============================================================================
# LIABILITIES (Phase 8C - Read-Only Financial Position Data)
# =============================================================================

def _normalize_liability_item(raw: dict, account_map: dict, liability_type: str) -> dict:
    """
    Normalize a liability item to standard output format.

    Returns dict with:
    - institution, account_name, account_mask, reported_balance,
    - interest_rate (if present), as_of timestamp

    NO risk scoring. NO recommendations. NO payoff projections.
    """
    account_id = raw.get("account_id")
    account_info = account_map.get(account_id, {})

    # Get balance - use last_payment_amount or current balance
    reported_balance = None
    if liability_type == "credit_card":
        reported_balance = raw.get("last_statement_balance") or raw.get("is_overdue")
    elif liability_type == "student_loan":
        reported_balance = raw.get("outstanding_interest_amount")
        if raw.get("loan_status", {}).get("type") == "repayment":
            reported_balance = raw.get("last_payment_amount")
    elif liability_type == "mortgage":
        reported_balance = raw.get("current_late_fee") or raw.get("escrow_balance")

    # Fall back to account balance if available
    if reported_balance is None:
        reported_balance = account_info.get("balances", {}).get("current")

    return {
        "account_id": account_id,
        "institution": account_info.get("official_name") or account_info.get("name", "Unknown Institution"),
        "account_name": account_info.get("name", "Unknown Account"),
        "account_mask": account_info.get("mask"),
        "reported_balance": reported_balance,
        "interest_rate": raw.get("aprs", [{}])[0].get("apr_percentage") if raw.get("aprs") else raw.get("interest_rate_percentage"),
        "as_of": raw.get("last_payment_date") or raw.get("last_statement_issue_date"),
        "liability_type": liability_type,
    }


@router.post("/liabilities/get", tags=["plaid-products", "liabilities"])
async def get_liabilities(
    payload: LiabilitiesGetRequest,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
) -> JSONResponse:
    """
    Get credit card and loan liabilities from Plaid (Read-Only Financial Position).

    MANUAL EXECUTION ONLY - invoked explicitly by authorized users.
    NO BACKGROUND REFRESH - synchronous Plaid API call only.
    NO MUTATION - read-only operation.

    OUTPUT RULES:
        - Data grouped by: credit_cards, student_loans, mortgages, other_loans
        - Each item includes: institution, account_name/mask, reported_balance,
          interest_rate (if present), as_of timestamp
        - NO risk scoring
        - NO recommendations
        - NO payoff projections

    LANGUAGE:
        - Uses "reported balance" (not "current balance")
        - Uses "as of" timestamps (not "real-time" or "live")

    Security:
        - Requires authenticated user context (get_current_context)
        - Org-isolated: Only gets liabilities for owned items
        - Audit logged: liabilities_viewed event
        - Structured error envelope with request_id
    """
    from plaid.model.liabilities_get_request import LiabilitiesGetRequest as PlaidLiabilitiesGetRequest

    request_id = validate_request_id(x_request_id)
    organization_id = ctx["org_id"]
    user_id = ctx["user_id"]
    item_id = payload.item_id

    # Get access token (ORG ISOLATION ENFORCED) - check early
    access_token = _get_access_token_for_item(organization_id, item_id)
    if not access_token:
        return error_response(404, "item_not_found", "Plaid item not found or not accessible", request_id)

    # Audit (FAIL-CLOSED) - liabilities_viewed event
    try:
        record_audit(
            actor=user_id,
            action="liabilities_viewed",
            entity="plaid_liabilities",
            entity_id=organization_id,
            payload={
                "item_id": item_id,
                "organization_id": organization_id,
            },
            request_id=request_id,
        )
    except AuditServiceError as e:
        logger.error(f"Audit failed for get_liabilities: {e}")
        return error_response(500, "audit_failed", "Audit recording failed", request_id)

    try:
        client = _get_plaid_client()

        request_params = PlaidLiabilitiesGetRequest(
            access_token=access_token,
        )

        response = client.liabilities_get(request_params)

        # Build account lookup map for institution/name resolution
        account_map = {}
        accounts_list = []
        if hasattr(response, 'accounts'):
            for acc in (response.accounts or []):
                acc_dict = acc.to_dict() if hasattr(acc, 'to_dict') else {}
                account_map[acc_dict.get("account_id")] = acc_dict
                # Build frontend-compatible account object
                balances = acc_dict.get("balances", {})
                accounts_list.append({
                    "account_id": acc_dict.get("account_id"),
                    "name": acc_dict.get("name"),
                    "official_name": acc_dict.get("official_name"),
                    "type": acc_dict.get("type"),
                    "subtype": acc_dict.get("subtype"),
                    "mask": acc_dict.get("mask"),
                    "balances": {
                        "available": balances.get("available"),
                        "current": balances.get("current"),
                    },
                })

        # Normalize and group liabilities per frontend contract
        # Frontend expects: liabilities: { credit: [], student: [], mortgage: [] }
        credit_items = []
        student_items = []
        mortgage_items = []

        if hasattr(response, 'liabilities'):
            liabilities = response.liabilities

            # Credit cards
            if hasattr(liabilities, 'credit') and liabilities.credit:
                for cc in liabilities.credit:
                    raw = cc.to_dict() if hasattr(cc, 'to_dict') else {}
                    credit_items.append(_normalize_liability_item(raw, account_map, "credit_card"))

            # Student loans
            if hasattr(liabilities, 'student') and liabilities.student:
                for sl in liabilities.student:
                    raw = sl.to_dict() if hasattr(sl, 'to_dict') else {}
                    student_items.append(_normalize_liability_item(raw, account_map, "student_loan"))

            # Mortgages
            if hasattr(liabilities, 'mortgage') and liabilities.mortgage:
                for m in liabilities.mortgage:
                    raw = m.to_dict() if hasattr(m, 'to_dict') else {}
                    mortgage_items.append(_normalize_liability_item(raw, account_map, "mortgage"))

        # Calculate simple totals (no inferred analytics)
        total_credit = sum(c.get("reported_balance") or 0 for c in credit_items)
        total_student = sum(s.get("reported_balance") or 0 for s in student_items)
        total_mortgage = sum(m.get("reported_balance") or 0 for m in mortgage_items)

        return JSONResponse(
            status_code=200,
            content=build_response(
                success=True,
                data={
                    # Frontend contract: liabilities grouped under "liabilities" key
                    "liabilities": {
                        "credit": credit_items,
                        "student": student_items,
                        "mortgage": mortgage_items,
                    },
                    # Frontend contract: accounts array
                    "accounts": accounts_list,

                    # Simple totals (no projections, no risk scores)
                    "totals": {
                        "credit_cards": round(total_credit, 2),
                        "student_loans": round(total_student, 2),
                        "mortgages": round(total_mortgage, 2),
                        "all_liabilities": round(total_credit + total_student + total_mortgage, 2),
                    },

                    # Metadata
                    "item_id": item_id,
                    "data_retrieved_at": datetime.now(timezone.utc).isoformat(),
                },
                message="Liabilities retrieved. Reported balances reflect data as of timestamps shown.",
                request_id=request_id,
            ),
            headers={"X-Request-ID": request_id},
        )

    except Exception as e:
        logger.error(f"Liabilities get failed: {e}")
        error_msg = str(e)
        if "PRODUCT_NOT_ENABLED" in error_msg or "INVALID_PRODUCT" in error_msg:
            return error_response(400, "product_not_enabled", "Liabilities product not enabled for this item", request_id)
        return error_response(500, "plaid_error", "Failed to get liabilities", request_id)


# =============================================================================
# TRANSACTION ENRICHMENT
# =============================================================================

@router.post("/enrich/transactions", tags=["plaid-products", "enrichment"])
async def enrich_transactions(
    payload: EnrichTransactionsRequest,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
) -> JSONResponse:
    """
    Enrich transactions with additional metadata from Plaid.

    MANUAL EXECUTION ONLY - invoked explicitly by authorized users.

    Transaction enrichment adds:
    - Merchant logos
    - Cleaned merchant names
    - Detailed categories
    - Location data

    NOTE: Enriched data is returned but NOT stored with source transactions.
    Store enriched data separately if persistence is needed.

    Security:
        - Requires authenticated user context
        - Audit logged
    """
    from plaid.model.transactions_enrich_request import TransactionsEnrichRequest
    from plaid.model.client_provided_transaction import ClientProvidedTransaction

    request_id = validate_request_id(x_request_id)
    organization_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # Audit (FAIL-CLOSED)
    try:
        record_audit(
            actor=user_id,
            action="plaid.enrich.transactions",
            entity="plaid",
            entity_id=organization_id,
            payload={
                "transaction_count": len(payload.transactions),
            },
            request_id=request_id,
        )
    except AuditServiceError as e:
        logger.error(f"Audit failed for enrich_transactions: {e}")
        return error_response(500, "audit_failed", "Audit recording failed", request_id)

    if not payload.transactions:
        return error_response(400, "no_transactions", "No transactions provided for enrichment", request_id)

    if len(payload.transactions) > 100:
        return error_response(400, "too_many_transactions", "Maximum 100 transactions per request", request_id)

    try:
        client = _get_plaid_client()

        # Convert to Plaid format
        client_transactions = []
        for i, tx in enumerate(payload.transactions):
            client_tx = ClientProvidedTransaction(
                id=tx.get("id", f"tx_{i}"),
                description=tx.get("description", tx.get("name", "")),
                amount=tx.get("amount", 0),
                iso_currency_code=tx.get("iso_currency_code", "USD"),
            )
            client_transactions.append(client_tx)

        request_params = TransactionsEnrichRequest(
            account_type="depository",
            transactions=client_transactions,
        )

        response = client.transactions_enrich(request_params)

        # Convert enriched transactions to serializable format
        enriched = []
        if hasattr(response, 'enriched_transactions'):
            for tx in response.enriched_transactions:
                enriched.append(tx.to_dict() if hasattr(tx, 'to_dict') else {})

        return JSONResponse(
            status_code=200,
            content=build_response(
                success=True,
                data={
                    "enriched_transactions": enriched,
                    "total": len(enriched),
                },
                message="Transactions enriched. NOTE: Store enriched data separately from source.",
                request_id=request_id,
            ),
            headers={"X-Request-ID": request_id},
        )

    except Exception as e:
        logger.error(f"Transaction enrichment failed: {e}")
        return error_response(500, "plaid_error", "Failed to enrich transactions", request_id)
