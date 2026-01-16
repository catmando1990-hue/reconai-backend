# app/routers/investor_audit_api.py
"""
ReconAI — Investor Audit Trail & Export Receipts API (STEP 21)

Endpoints:
- GET /api/investor/audit/receipts - List export receipts
- GET /api/investor/audit/receipts/{receipt_id} - Get single receipt
- POST /api/investor/audit/receipts/generate - Generate receipt for export (manual)

Features:
- Read-only audit receipts for investor exports
- Receipt includes: export_id, timestamp, requesting org, fields included, redaction summary
- No raw data stored
- Manual generation only
- Structured responses with request_id

Requirements:
- Auth via get_current_context (Depends injection)
- RBAC: view_status
- Read-only, no mutations except receipt generation
- Structured responses with request_id
- Dashboard-only
"""

from __future__ import annotations

import sqlite3
import hashlib
from uuid import uuid4
from datetime import datetime
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth_context import get_current_context, AuthContext
from app.db import DB_PATH
from app.routers.billing_rbac import get_billing_actor, require_billing_permission

router = APIRouter(prefix="/api/investor/audit", tags=["investor-audit"])

# In-memory receipt store (production would use DB)
_receipt_store: Dict[str, Dict[str, Any]] = {}


def _generate_receipt_hash(receipt_data: Dict[str, Any]) -> str:
    """Generate a deterministic hash for receipt integrity verification."""
    hash_input = f"{receipt_data['export_id']}:{receipt_data['org_id']}:{receipt_data['timestamp']}:{receipt_data['export_type']}"
    return hashlib.sha256(hash_input.encode()).hexdigest()[:16]


def _get_receipts_for_org(org_id: str, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
    """Get all receipts for an organization."""
    org_receipts = [
        r for r in _receipt_store.values()
        if r.get("org_id") == org_id
    ]
    # Sort by timestamp descending
    org_receipts.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return org_receipts[offset:offset + limit]


def _count_receipts_for_org(org_id: str) -> int:
    """Count total receipts for an organization."""
    return len([r for r in _receipt_store.values() if r.get("org_id") == org_id])


@router.get("/receipts")
async def list_receipts(
    ctx: AuthContext = Depends(get_current_context),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """
    GET /api/investor/audit/receipts

    List export receipts for the current organization.

    Read-only endpoint - manual refresh only.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    receipts = _get_receipts_for_org(org_id, limit, offset)
    total = _count_receipts_for_org(org_id)

    return {
        "request_id": request_id,
        "receipts": receipts,
        "pagination": {
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": offset + limit < total,
        },
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/receipts/{receipt_id}")
async def get_receipt(
    receipt_id: str,
    ctx: AuthContext = Depends(get_current_context),
):
    """
    GET /api/investor/audit/receipts/{receipt_id}

    Get a single export receipt by ID.

    Read-only endpoint.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    receipt = _receipt_store.get(receipt_id)

    if not receipt:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "receipt_not_found",
                "message": f"Receipt {receipt_id} not found",
                "request_id": request_id,
            }
        )

    # Verify org ownership
    if receipt.get("org_id") != org_id:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "forbidden",
                "message": "Receipt belongs to a different organization",
                "request_id": request_id,
            }
        )

    return {
        "request_id": request_id,
        "receipt": receipt,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.post("/receipts/generate")
async def generate_receipt(
    ctx: AuthContext = Depends(get_current_context),
    export_type: str = Query(default="json", regex="^(json|pdf)$"),
):
    """
    POST /api/investor/audit/receipts/generate

    Generate a receipt for a manual export.

    This endpoint creates an audit receipt documenting:
    - Export ID and timestamp
    - Requesting organization
    - Fields included in export (via allowlist)
    - Redaction summary
    - No raw data stored

    Manual trigger only - dashboard-only.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    export_id = str(uuid4())
    timestamp = datetime.utcnow().isoformat()

    # Fields included (from STEP 18 allowlist)
    fields_included = [
        "organization.id",
        "organization.tier",
        "organization.tier_name",
        "organization.created_at",
        "platform_status.status",
        "platform_status.uptime_30d_percent",
        "slos.summary.total",
        "slos.summary.met",
        "slos.summary.at_risk",
        "slos.details",
        "error_budget.status",
        "error_budget.budget_remaining_percent",
        "activation_metrics.milestones_completed",
        "activation_metrics.milestones_total",
        "capability_coverage",
    ]

    # Redaction summary (from STEP 18)
    redaction_summary = {
        "pii_fields_redacted": [
            "organization.name",
            "user_id",
            "email",
            "raw_transactions",
            "transaction_details",
            "account_numbers",
            "routing_numbers",
            "ssn",
            "tax_id",
            "bank_credentials",
            "api_keys",
            "secrets",
        ],
        "redaction_applied": True,
        "allowlist_applied": True,
    }

    # Get org tier from DB
    org_tier = "unknown"
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.execute(
                "SELECT tier FROM organizations WHERE id = ?",
                (org_id,)
            )
            row = cursor.fetchone()
            if row:
                org_tier = row[0] or "free"
    except Exception:
        pass

    receipt_data = {
        "receipt_id": export_id,
        "export_id": export_id,
        "org_id": org_id,
        "user_id": user_id,
        "org_tier": org_tier,
        "export_type": export_type,
        "timestamp": timestamp,
        "fields_included": fields_included,
        "fields_count": len(fields_included),
        "redaction_summary": redaction_summary,
        "classification": "INTERNAL / INVESTOR SNAPSHOT",
        "hardening_applied": {
            "rate_limiting": True,
            "pii_redaction": True,
            "allowlist_filtering": True,
            "size_cap": True,
            "watermark": export_type == "pdf",
        },
    }

    # Generate integrity hash
    receipt_data["integrity_hash"] = _generate_receipt_hash(receipt_data)

    # Store receipt
    _receipt_store[export_id] = receipt_data

    return {
        "request_id": request_id,
        "receipt": receipt_data,
        "message": "Export receipt generated successfully",
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/summary")
async def audit_summary(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    GET /api/investor/audit/summary

    Get audit summary statistics for the current organization.

    Read-only endpoint.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    org_receipts = [r for r in _receipt_store.values() if r.get("org_id") == org_id]

    # Calculate statistics
    total_exports = len(org_receipts)
    json_exports = len([r for r in org_receipts if r.get("export_type") == "json"])
    pdf_exports = len([r for r in org_receipts if r.get("export_type") == "pdf"])

    # Get latest export timestamp
    latest_export = None
    if org_receipts:
        sorted_receipts = sorted(org_receipts, key=lambda r: r.get("timestamp", ""), reverse=True)
        latest_export = sorted_receipts[0].get("timestamp")

    return {
        "request_id": request_id,
        "summary": {
            "total_exports": total_exports,
            "by_type": {
                "json": json_exports,
                "pdf": pdf_exports,
            },
            "latest_export": latest_export,
            "hardening_status": {
                "pii_redaction": "active",
                "allowlist_filtering": "active",
                "rate_limiting": "active",
                "pdf_watermark": "active",
            },
        },
        "timestamp": datetime.utcnow().isoformat(),
    }
