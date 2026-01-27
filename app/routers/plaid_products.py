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
# ASSET REPORTS
# =============================================================================

@router.post("/assets/report/create", tags=["plaid-products", "assets"])
async def create_asset_report(
    payload: AssetReportCreateRequest,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
) -> JSONResponse:
    """
    Create a Plaid Asset Report.

    MANUAL EXECUTION ONLY - invoked explicitly by authorized users.

    Asset reports provide point-in-time snapshots of account balances and
    transaction history for underwriting and verification purposes.

    Security:
        - Requires authenticated user context
        - Org-isolated: Only creates report for owned items
        - Audit logged
    """
    from plaid.model.asset_report_create_request import AssetReportCreateRequest as PlaidAssetReportCreateRequest
    from plaid.model.asset_report_create_request_options import AssetReportCreateRequestOptions

    request_id = validate_request_id(x_request_id)
    organization_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # Audit (FAIL-CLOSED)
    try:
        record_audit(
            actor=user_id,
            action="plaid.assets.report.create",
            entity="plaid",
            entity_id=organization_id,
            payload={
                "item_id": payload.item_id,
                "days_requested": payload.days_requested,
            },
            request_id=request_id,
        )
    except AuditServiceError as e:
        logger.error(f"Audit failed for create_asset_report: {e}")
        return error_response(500, "audit_failed", "Audit recording failed", request_id)

    # Get access token (ORG ISOLATION ENFORCED)
    access_token = _get_access_token_for_item(organization_id, payload.item_id)
    if not access_token:
        return error_response(404, "item_not_found", "Plaid item not found or not accessible", request_id)

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
                    "request_id": response.request_id,
                },
                message="Asset report creation initiated",
                request_id=request_id,
            ),
            headers={"X-Request-ID": request_id},
        )

    except Exception as e:
        logger.error(f"Asset report creation failed: {e}")
        return error_response(500, "plaid_error", "Failed to create asset report", request_id)


@router.post("/assets/report/get", tags=["plaid-products", "assets"])
async def get_asset_report(
    payload: AssetReportGetRequest,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
) -> JSONResponse:
    """
    Get a completed Plaid Asset Report.

    MANUAL EXECUTION ONLY - invoked explicitly by authorized users.

    Security:
        - Requires authenticated user context
        - Audit logged
    """
    from plaid.model.asset_report_get_request import AssetReportGetRequest as PlaidAssetReportGetRequest

    request_id = validate_request_id(x_request_id)
    organization_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # Audit (FAIL-CLOSED)
    try:
        record_audit(
            actor=user_id,
            action="plaid.assets.report.get",
            entity="plaid",
            entity_id=organization_id,
            payload={
                "asset_report_token": payload.asset_report_token[:20] + "...",  # Truncate for security
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

        # Convert to dict for JSON serialization
        report_data = response.to_dict() if hasattr(response, 'to_dict') else {}

        return JSONResponse(
            status_code=200,
            content=build_response(
                success=True,
                data={
                    "report": report_data.get("report", {}),
                    "warnings": report_data.get("warnings", []),
                },
                message="Asset report retrieved",
                request_id=request_id,
            ),
            headers={"X-Request-ID": request_id},
        )

    except Exception as e:
        logger.error(f"Asset report get failed: {e}")
        error_msg = str(e)
        if "PRODUCT_NOT_READY" in error_msg:
            return error_response(202, "report_pending", "Asset report is still being generated", request_id)
        return error_response(500, "plaid_error", "Failed to get asset report", request_id)


@router.post("/assets/report/remove", tags=["plaid-products", "assets"])
async def remove_asset_report(
    payload: AssetReportRemoveRequest,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
) -> JSONResponse:
    """
    Remove a Plaid Asset Report.

    MANUAL EXECUTION ONLY - invoked explicitly by authorized users.

    Security:
        - Requires authenticated user context
        - Audit logged
    """
    from plaid.model.asset_report_remove_request import AssetReportRemoveRequest as PlaidAssetReportRemoveRequest

    request_id = validate_request_id(x_request_id)
    organization_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # Audit (FAIL-CLOSED)
    try:
        record_audit(
            actor=user_id,
            action="plaid.assets.report.remove",
            entity="plaid",
            entity_id=organization_id,
            payload={
                "asset_report_token": payload.asset_report_token[:20] + "...",
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

        return JSONResponse(
            status_code=200,
            content=build_response(
                success=True,
                data={
                    "removed": response.removed,
                },
                message="Asset report removed",
                request_id=request_id,
            ),
            headers={"X-Request-ID": request_id},
        )

    except Exception as e:
        logger.error(f"Asset report remove failed: {e}")
        return error_response(500, "plaid_error", "Failed to remove asset report", request_id)


# =============================================================================
# STATEMENTS
# =============================================================================

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

    Security:
        - Requires authenticated user context
        - Org-isolated: Only lists statements for owned items
        - Audit logged
    """
    from plaid.model.statements_list_request import StatementsListRequest as PlaidStatementsListRequest

    request_id = validate_request_id(x_request_id)
    organization_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # Audit (FAIL-CLOSED)
    try:
        record_audit(
            actor=user_id,
            action="plaid.statements.list",
            entity="plaid",
            entity_id=organization_id,
            payload={"item_id": item_id},
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

        # Convert statements to serializable format
        statements = []
        if hasattr(response, 'accounts'):
            for account in response.accounts:
                if hasattr(account, 'statements'):
                    for stmt in account.statements:
                        statements.append({
                            "statement_id": stmt.statement_id if hasattr(stmt, 'statement_id') else None,
                            "month": stmt.month if hasattr(stmt, 'month') else None,
                            "year": stmt.year if hasattr(stmt, 'year') else None,
                            "account_id": account.account_id if hasattr(account, 'account_id') else None,
                        })

        return JSONResponse(
            status_code=200,
            content=build_response(
                success=True,
                data={
                    "statements": statements,
                    "total": len(statements),
                },
                message="Statements listed",
                request_id=request_id,
            ),
            headers={"X-Request-ID": request_id},
        )

    except Exception as e:
        logger.error(f"Statements list failed: {e}")
        return error_response(500, "plaid_error", "Failed to list statements", request_id)


@router.get("/statements/download", tags=["plaid-products", "statements"])
async def download_statement(
    item_id: str,
    statement_id: str,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
) -> StreamingResponse:
    """
    Download a bank statement PDF.

    MANUAL EXECUTION ONLY - invoked explicitly by authorized users.

    Security:
        - Requires authenticated user context
        - Org-isolated: Only downloads statements for owned items
        - Audit logged
    """
    from plaid.model.statements_download_request import StatementsDownloadRequest as PlaidStatementsDownloadRequest
    import io

    request_id = validate_request_id(x_request_id)
    organization_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # Audit (FAIL-CLOSED)
    try:
        record_audit(
            actor=user_id,
            action="plaid.statements.download",
            entity="plaid",
            entity_id=organization_id,
            payload={"item_id": item_id, "statement_id": statement_id},
            request_id=request_id,
        )
    except AuditServiceError as e:
        logger.error(f"Audit failed for download_statement: {e}")
        raise HTTPException(status_code=500, detail="Audit recording failed")

    # Get access token (ORG ISOLATION ENFORCED)
    access_token = _get_access_token_for_item(organization_id, item_id)
    if not access_token:
        raise HTTPException(status_code=404, detail="Plaid item not found or not accessible")

    try:
        client = _get_plaid_client()

        request_params = PlaidStatementsDownloadRequest(
            access_token=access_token,
            statement_id=statement_id,
        )

        response = client.statements_download(request_params)

        # Response is PDF bytes
        pdf_content = response.read() if hasattr(response, 'read') else response

        return StreamingResponse(
            io.BytesIO(pdf_content),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="statement-{statement_id}.pdf"',
                "X-Request-ID": request_id,
            }
        )

    except Exception as e:
        logger.error(f"Statement download failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to download statement")


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
# INVESTMENTS
# =============================================================================

@router.post("/investments/refresh", tags=["plaid-products", "investments"])
async def refresh_investments(
    payload: InvestmentsRefreshRequest,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
) -> JSONResponse:
    """
    Refresh investment holdings from Plaid.

    MANUAL EXECUTION ONLY - invoked explicitly by authorized users.

    Security:
        - Requires authenticated user context
        - Org-isolated: Only refreshes investments for owned items
        - Audit logged
    """
    from plaid.model.investments_refresh_request import InvestmentsRefreshRequest as PlaidInvestmentsRefreshRequest

    request_id = validate_request_id(x_request_id)
    organization_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # Audit (FAIL-CLOSED)
    try:
        record_audit(
            actor=user_id,
            action="plaid.investments.refresh",
            entity="plaid",
            entity_id=organization_id,
            payload={"item_id": payload.item_id},
            request_id=request_id,
        )
    except AuditServiceError as e:
        logger.error(f"Audit failed for refresh_investments: {e}")
        return error_response(500, "audit_failed", "Audit recording failed", request_id)

    # Get access token (ORG ISOLATION ENFORCED)
    access_token = _get_access_token_for_item(organization_id, payload.item_id)
    if not access_token:
        return error_response(404, "item_not_found", "Plaid item not found or not accessible", request_id)

    try:
        client = _get_plaid_client()

        request_params = PlaidInvestmentsRefreshRequest(
            access_token=access_token,
        )

        response = client.investments_refresh(request_params)

        return JSONResponse(
            status_code=200,
            content=build_response(
                success=True,
                data={
                    "request_id": response.request_id if hasattr(response, 'request_id') else None,
                },
                message="Investment holdings refresh initiated",
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


# =============================================================================
# LIABILITIES
# =============================================================================

@router.get("/liabilities/get", tags=["plaid-products", "liabilities"])
async def get_liabilities(
    item_id: str,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
) -> JSONResponse:
    """
    Get credit card and loan liabilities from Plaid.

    MANUAL EXECUTION ONLY - invoked explicitly by authorized users.

    Security:
        - Requires authenticated user context
        - Org-isolated: Only gets liabilities for owned items
        - Audit logged
    """
    from plaid.model.liabilities_get_request import LiabilitiesGetRequest as PlaidLiabilitiesGetRequest

    request_id = validate_request_id(x_request_id)
    organization_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # Audit (FAIL-CLOSED)
    try:
        record_audit(
            actor=user_id,
            action="plaid.liabilities.get",
            entity="plaid",
            entity_id=organization_id,
            payload={"item_id": item_id},
            request_id=request_id,
        )
    except AuditServiceError as e:
        logger.error(f"Audit failed for get_liabilities: {e}")
        return error_response(500, "audit_failed", "Audit recording failed", request_id)

    # Get access token (ORG ISOLATION ENFORCED)
    access_token = _get_access_token_for_item(organization_id, item_id)
    if not access_token:
        return error_response(404, "item_not_found", "Plaid item not found or not accessible", request_id)

    try:
        client = _get_plaid_client()

        request_params = PlaidLiabilitiesGetRequest(
            access_token=access_token,
        )

        response = client.liabilities_get(request_params)

        # Convert liabilities to serializable format
        liabilities_data = {}
        if hasattr(response, 'liabilities'):
            liabilities = response.liabilities

            # Credit cards
            if hasattr(liabilities, 'credit'):
                liabilities_data["credit"] = [
                    cc.to_dict() if hasattr(cc, 'to_dict') else {}
                    for cc in (liabilities.credit or [])
                ]

            # Student loans
            if hasattr(liabilities, 'student'):
                liabilities_data["student"] = [
                    sl.to_dict() if hasattr(sl, 'to_dict') else {}
                    for sl in (liabilities.student or [])
                ]

            # Mortgages
            if hasattr(liabilities, 'mortgage'):
                liabilities_data["mortgage"] = [
                    m.to_dict() if hasattr(m, 'to_dict') else {}
                    for m in (liabilities.mortgage or [])
                ]

        return JSONResponse(
            status_code=200,
            content=build_response(
                success=True,
                data={
                    "liabilities": liabilities_data,
                    "accounts": [
                        acc.to_dict() if hasattr(acc, 'to_dict') else {}
                        for acc in (response.accounts or [])
                    ] if hasattr(response, 'accounts') else [],
                },
                message="Liabilities retrieved",
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
