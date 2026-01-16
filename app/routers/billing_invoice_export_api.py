# app/routers/billing_invoice_export_api.py
"""
ReconAI Billing — Invoice Export API (Read-Only)

POST /api/billing/invoices/export - Generate invoice export pack (manual trigger)

Requirements:
- Auth via get_current_context (Depends injection)
- RBAC: view_invoices permission required
- Read-only (no mutations to billing state)
- Manual invocation only (no auto-export)
- Structured responses with request_id
- Fail-closed in production if Stripe secrets missing
"""

from __future__ import annotations

import os
import sqlite3
from uuid import uuid4
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth_context import get_current_context, AuthContext
from app.db import DB_PATH
from .billing_rbac import get_billing_actor, require_billing_permission
from .stripe_linking_hardening import validate_customer_subscription_link

router = APIRouter(tags=["billing"])

# Optional: Import Stripe SDK if available
try:
    import stripe
    STRIPE_AVAILABLE = True
except ImportError:
    STRIPE_AVAILABLE = False


class ExportRequest(BaseModel):
    start_date: Optional[str] = None  # ISO date string
    end_date: Optional[str] = None    # ISO date string
    format: str = "json"              # json | csv


def _get_stripe_customer_id(org_id: str) -> Optional[str]:
    """Get Stripe customer ID for an organization."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "SELECT stripe_customer_id, stripe_subscription_id FROM organizations WHERE id = ?",
            (org_id,)
        )
        row = cursor.fetchone()
        if row and row[0]:
            # Validate linkage
            try:
                validate_customer_subscription_link(row[0], row[1])
            except ValueError:
                return None
            return row[0]
        return None


def _format_invoice_for_export(inv: Dict[str, Any]) -> Dict[str, Any]:
    """Format a Stripe invoice for export (safe fields only)."""
    return {
        "invoice_id": inv.get("id"),
        "invoice_number": inv.get("number"),
        "status": inv.get("status"),
        "created_at": datetime.fromtimestamp(inv.get("created", 0)).isoformat() if inv.get("created") else None,
        "due_date": datetime.fromtimestamp(inv.get("due_date", 0)).isoformat() if inv.get("due_date") else None,
        "amount_due": inv.get("amount_due", 0) / 100,  # Convert from cents
        "amount_paid": inv.get("amount_paid", 0) / 100,
        "total": inv.get("total", 0) / 100,
        "currency": inv.get("currency", "usd").upper(),
        "period_start": datetime.fromtimestamp(inv.get("period_start", 0)).isoformat() if inv.get("period_start") else None,
        "period_end": datetime.fromtimestamp(inv.get("period_end", 0)).isoformat() if inv.get("period_end") else None,
        "hosted_invoice_url": inv.get("hosted_invoice_url"),
        "invoice_pdf": inv.get("invoice_pdf"),
    }


def _generate_csv(invoices: List[Dict[str, Any]]) -> str:
    """Generate CSV string from invoice data."""
    if not invoices:
        return "invoice_id,invoice_number,status,created_at,amount_due,amount_paid,total,currency\n"

    headers = ["invoice_id", "invoice_number", "status", "created_at", "amount_due", "amount_paid", "total", "currency"]
    lines = [",".join(headers)]

    for inv in invoices:
        row = [str(inv.get(h, "")) for h in headers]
        lines.append(",".join(row))

    return "\n".join(lines)


@router.post("/api/billing/invoices/export")
async def export_invoices(
    payload: ExportRequest,
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Generate an invoice export pack for the organization.

    Manual trigger only - no automatic exports.
    Returns invoice data in requested format (JSON or CSV).
    RBAC: view_invoices permission required.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check: view_invoices permission required
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_invoices", request_id)

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
            "export": "ready",
            "format": payload.format,
            "invoices": [],
            "notes": "Stripe not configured (dev mode)",
        }

    if not STRIPE_AVAILABLE:
        return {
            "request_id": request_id,
            "org_id": org_id,
            "export": "ready",
            "format": payload.format,
            "invoices": [],
            "notes": "Stripe SDK not installed",
        }

    # Get Stripe customer ID with linkage validation
    stripe_customer_id = _get_stripe_customer_id(org_id)

    if not stripe_customer_id:
        return {
            "request_id": request_id,
            "org_id": org_id,
            "export": "ready",
            "format": payload.format,
            "invoices": [],
            "notes": "No valid Stripe customer linked to this organization",
        }

    # Fetch invoices from Stripe
    try:
        stripe.api_key = stripe_secret

        # Build query params
        params = {
            "customer": stripe_customer_id,
            "limit": 100,
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

        formatted = [_format_invoice_for_export(inv) for inv in invoices.data]

        # LAW 4: Audit log export BEFORE returning (must be reachable)
        try:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("""
                    INSERT INTO audit_log (id, action, actor, metadata, created_at)
                    VALUES (?, ?, ?, ?, datetime('now'))
                """, (
                    request_id,
                    "BILLING_INVOICE_EXPORT",
                    user_id,
                    str({"org_id": org_id, "format": payload.format, "count": len(formatted)}),
                ))
                conn.commit()
        except Exception:
            pass  # Audit logging should not fail the request

        # Generate export in requested format
        if payload.format == "csv":
            csv_data = _generate_csv(formatted)
            return {
                "request_id": request_id,
                "org_id": org_id,
                "export": "ready",
                "format": "csv",
                "data": csv_data,
                "count": len(formatted),
            }

        # Default: JSON format
        return {
            "request_id": request_id,
            "org_id": org_id,
            "export": "ready",
            "format": "json",
            "invoices": formatted,
            "count": len(formatted),
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
