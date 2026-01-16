# app/routers/billing_erp_exports_api.py
"""
ReconAI Billing — ERP Export API

Endpoints:
- GET /api/billing/erp/formats - List available ERP export formats
- POST /api/billing/erp/export - Generate ERP-compatible CSV export (manual)

Features:
- NetSuite CSV mapping
- QuickBooks CSV mapping
- Manual trigger only (no auto-sync)
- Bounded queries with limits

Requirements:
- Auth via get_current_context (Depends injection)
- RBAC: view_invoices permission required
- Manual invocation only (no polling/auto-sync)
- Structured responses with request_id
- Fail-closed in production if Stripe secrets missing
"""

from __future__ import annotations

import os
import json
import sqlite3
from uuid import uuid4
from datetime import datetime
from typing import Optional, Dict, Any, List
from io import StringIO
import csv

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth_context import get_current_context, AuthContext
from app.db import DB_PATH
from .billing_rbac import get_billing_actor, require_billing_permission

router = APIRouter(tags=["billing-erp"])

# Optional Stripe SDK
try:
    import stripe
    STRIPE_AVAILABLE = True
except ImportError:
    STRIPE_AVAILABLE = False


class ErpExportRequest(BaseModel):
    format: str  # "netsuite" | "quickbooks"
    start_date: Optional[str] = None
    end_date: Optional[str] = None


# ERP CSV column mappings
NETSUITE_COLUMNS = [
    "External ID",
    "Customer",
    "Transaction Date",
    "Amount",
    "Currency",
    "Status",
    "Invoice Number",
    "Description",
    "GL Account",
]

QUICKBOOKS_COLUMNS = [
    "Customer",
    "Invoice No",
    "Date",
    "Total",
    "Status",
    "Memo",
]


def _format_invoice_netsuite(inv: Dict[str, Any]) -> List[str]:
    """Format invoice for NetSuite CSV."""
    return [
        inv.get("id", ""),
        inv.get("customer_name", ""),
        datetime.fromtimestamp(inv.get("created", 0)).strftime("%Y-%m-%d") if inv.get("created") else "",
        str(inv.get("total", 0) / 100) if inv.get("total") else "0.00",
        inv.get("currency", "USD").upper(),
        inv.get("status", ""),
        inv.get("number", ""),
        f"Invoice {inv.get('number', '')}",
        "1200",  # Default AR account
    ]


def _format_invoice_quickbooks(inv: Dict[str, Any]) -> List[str]:
    """Format invoice for QuickBooks CSV."""
    return [
        inv.get("customer_name", ""),
        inv.get("number", ""),
        datetime.fromtimestamp(inv.get("created", 0)).strftime("%m/%d/%Y") if inv.get("created") else "",
        str(inv.get("total", 0) / 100) if inv.get("total") else "0.00",
        inv.get("status", ""),
        f"Stripe Invoice {inv.get('id', '')}",
    ]


def _generate_csv(columns: List[str], rows: List[List[str]]) -> str:
    """Generate CSV string from columns and rows."""
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(columns)
    writer.writerows(rows)
    return output.getvalue()


def _get_stripe_customer_id(org_id: str) -> Optional[str]:
    """Get Stripe customer ID for an organization."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "SELECT stripe_customer_id FROM organizations WHERE id = ?",
            (org_id,)
        )
        row = cursor.fetchone()
        return row[0] if row and row[0] else None


@router.get("/api/billing/erp/formats")
async def list_erp_formats(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    List available ERP export formats.

    Read-only endpoint - no mutations.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    return {
        "request_id": request_id,
        "org_id": org_id,
        "formats": [
            {
                "id": "netsuite",
                "name": "NetSuite",
                "description": "Oracle NetSuite compatible CSV format",
                "columns": NETSUITE_COLUMNS,
            },
            {
                "id": "quickbooks",
                "name": "QuickBooks",
                "description": "Intuit QuickBooks compatible CSV format",
                "columns": QUICKBOOKS_COLUMNS,
            },
        ],
    }


@router.post("/api/billing/erp/export")
async def export_erp_data(
    payload: ErpExportRequest,
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Generate ERP-compatible CSV export.

    Manual trigger only - no auto-sync.
    RBAC: view_invoices permission required.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_invoices", request_id)

    # Validate format
    valid_formats = ["netsuite", "quickbooks"]
    if payload.format not in valid_formats:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "INVALID_FORMAT",
                "message": f"Format must be one of: {', '.join(valid_formats)}",
                "request_id": request_id,
            }
        )

    # LAW 5: Fail-closed in production if Stripe secrets missing
    stripe_secret = os.getenv("STRIPE_SECRET_KEY")
    if not stripe_secret:
        env = os.getenv("ENVIRONMENT") or os.getenv("ENV") or os.getenv("NODE_ENV")
        if env == "production":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": "STRIPE_NOT_CONFIGURED",
                    "message": "Stripe API key not configured",
                    "request_id": request_id,
                }
            )
        # Dev mode: return stub
        return {
            "request_id": request_id,
            "org_id": org_id,
            "format": payload.format,
            "data": "",
            "count": 0,
            "notes": "Stripe not configured (dev mode)",
        }

    if not STRIPE_AVAILABLE:
        return {
            "request_id": request_id,
            "org_id": org_id,
            "format": payload.format,
            "data": "",
            "count": 0,
            "notes": "Stripe SDK not installed",
        }

    # Get Stripe customer ID
    stripe_customer_id = _get_stripe_customer_id(org_id)

    if not stripe_customer_id:
        return {
            "request_id": request_id,
            "org_id": org_id,
            "format": payload.format,
            "data": "",
            "count": 0,
            "notes": "No Stripe customer linked",
        }

    # Fetch invoices from Stripe
    try:
        stripe.api_key = stripe_secret

        params = {
            "customer": stripe_customer_id,
            "limit": 100,  # Bounded query
        }

        # Add date filters if provided
        if payload.start_date:
            try:
                start_dt = datetime.fromisoformat(payload.start_date.replace("Z", "+00:00"))
                params["created"] = {"gte": int(start_dt.timestamp())}
            except ValueError:
                pass

        if payload.end_date:
            try:
                end_dt = datetime.fromisoformat(payload.end_date.replace("Z", "+00:00"))
                if "created" in params:
                    params["created"]["lte"] = int(end_dt.timestamp())
                else:
                    params["created"] = {"lte": int(end_dt.timestamp())}
            except ValueError:
                pass

        invoices = stripe.Invoice.list(**params)

        # Format based on ERP type
        if payload.format == "netsuite":
            columns = NETSUITE_COLUMNS
            rows = [_format_invoice_netsuite(inv) for inv in invoices.data]
        else:  # quickbooks
            columns = QUICKBOOKS_COLUMNS
            rows = [_format_invoice_quickbooks(inv) for inv in invoices.data]

        # Audit log BEFORE returning
        try:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("""
                    INSERT INTO audit_log (id, action, actor, metadata, created_at)
                    VALUES (?, ?, ?, ?, datetime('now'))
                """, (
                    request_id,
                    "BILLING_ERP_EXPORT",
                    user_id,
                    json.dumps({"org_id": org_id, "format": payload.format, "count": len(rows)}),
                ))
                conn.commit()
        except Exception:
            pass

        csv_data = _generate_csv(columns, rows)

        return {
            "request_id": request_id,
            "org_id": org_id,
            "format": payload.format,
            "data": csv_data,
            "count": len(rows),
            "columns": columns,
        }

    except stripe.error.StripeError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "STRIPE_API_ERROR",
                "message": str(e.user_message) if hasattr(e, 'user_message') else "Stripe API error",
                "request_id": request_id,
            }
        )
