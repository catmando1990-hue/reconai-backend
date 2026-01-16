# app/routers/investor_export_api.py
"""
ReconAI — Investor Narrative Export API (STEP 16 + STEP 18 Hardening + STEP 24 Kill-Switch)

Endpoints:
- GET /api/investor/export/json - JSON snapshot (machine-readable)
- GET /api/investor/export/pdf - PDF snapshot (human-readable)
- GET /api/investor/export/status - Export capability status

Features:
- Platform status snapshot
- SLOs & error budget
- Activation metrics
- Capability coverage by tier
- Manual trigger only (no background jobs)

STEP 18 Hardening:
- Allowlist-based field selection (explicit include list)
- PII redaction (no raw transaction data)
- Rate limits and request size caps
- PDF watermark: "INTERNAL / INVESTOR SNAPSHOT"
- Generation timestamp on all exports

STEP 24 Kill-Switch:
- Kill-switch guard on export endpoints
- FAIL CLOSED with structured error + request_id

Requirements:
- Auth via get_current_context (Depends injection)
- RBAC: view_status
- Read-only, no mutations
- Structured responses with request_id
"""

from __future__ import annotations

import json
import sqlite3
import time
from uuid import uuid4
from datetime import datetime
from typing import Dict, Any, List, Set
from io import BytesIO
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, Response

from app.auth_context import get_current_context, AuthContext
from app.db import DB_PATH
from app.entitlements import TIER_LIMITS, get_tier_limits, guard_feature_killswitch
from app.routers.billing_rbac import get_billing_actor, require_billing_permission

router = APIRouter(prefix="/api/investor/export", tags=["investor-export"])


# ============================================================================
# STEP 18: Hardening Configuration
# ============================================================================

# Allowlist of fields that can be included in exports (explicit include)
ALLOWED_EXPORT_FIELDS: Set[str] = {
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
}

# Fields that must NEVER appear in exports (PII/sensitive data)
REDACTED_FIELDS: Set[str] = {
    "organization.name",  # Org name could be PII
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
}

# Rate limiting: track requests per org
_rate_limit_cache: Dict[str, List[float]] = defaultdict(list)
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_REQUESTS = 10

# Request size cap (max response size in bytes)
MAX_RESPONSE_SIZE_BYTES = 1024 * 1024  # 1MB


def _check_rate_limit(org_id: str, request_id: str) -> None:
    """
    Enforce rate limiting per organization.

    Raises HTTPException if rate limit exceeded.
    """
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW_SECONDS

    # Clean old entries
    _rate_limit_cache[org_id] = [
        ts for ts in _rate_limit_cache[org_id] if ts > window_start
    ]

    # Check limit
    if len(_rate_limit_cache[org_id]) >= RATE_LIMIT_MAX_REQUESTS:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "rate_limit_exceeded",
                "message": f"Maximum {RATE_LIMIT_MAX_REQUESTS} export requests per {RATE_LIMIT_WINDOW_SECONDS} seconds",
                "request_id": request_id,
                "retry_after_seconds": RATE_LIMIT_WINDOW_SECONDS,
            }
        )

    # Record this request
    _rate_limit_cache[org_id].append(now)


def _redact_pii(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Redact PII and sensitive data from export payload.

    Removes any fields that match REDACTED_FIELDS patterns.
    """
    def _redact_recursive(obj: Any, path: str = "") -> Any:
        if isinstance(obj, dict):
            result = {}
            for key, value in obj.items():
                full_path = f"{path}.{key}" if path else key
                # Skip redacted fields
                if key in REDACTED_FIELDS or full_path in REDACTED_FIELDS:
                    continue
                # Check if any redacted field pattern matches
                if any(rf in full_path.lower() for rf in ["email", "ssn", "account_number", "routing", "password", "secret", "key", "token"]):
                    continue
                result[key] = _redact_recursive(value, full_path)
            return result
        elif isinstance(obj, list):
            return [_redact_recursive(item, path) for item in obj]
        else:
            return obj

    return _redact_recursive(data)


def _apply_allowlist(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply allowlist filtering to export data.

    Only includes fields that are explicitly in ALLOWED_EXPORT_FIELDS.
    This is a defense-in-depth measure on top of redaction.
    """
    def _is_path_allowed(path: str) -> bool:
        # Check exact match
        if path in ALLOWED_EXPORT_FIELDS:
            return True
        # Check if any allowed field is a prefix (allows nested data)
        for allowed in ALLOWED_EXPORT_FIELDS:
            if path.startswith(f"{allowed}.") or allowed.startswith(f"{path}."):
                return True
        return False

    def _filter_recursive(obj: Any, path: str = "") -> Any:
        if isinstance(obj, dict):
            result = {}
            for key, value in obj.items():
                full_path = f"{path}.{key}" if path else key
                if _is_path_allowed(full_path):
                    filtered_value = _filter_recursive(value, full_path)
                    if filtered_value is not None:
                        result[key] = filtered_value
            return result if result else None
        elif isinstance(obj, list):
            return [_filter_recursive(item, path) for item in obj]
        else:
            return obj

    return _filter_recursive(data) or {}


# SLO Definitions (from production_readiness_api)
SLOS = [
    {"id": "availability", "name": "Service Availability", "target": 99.9, "unit": "percent", "current_value": 99.95, "status": "met"},
    {"id": "latency_p50", "name": "P50 Latency", "target": 100, "unit": "ms", "current_value": 45, "status": "met"},
    {"id": "latency_p99", "name": "P99 Latency", "target": 500, "unit": "ms", "current_value": 320, "status": "met"},
    {"id": "error_rate", "name": "Error Rate", "target": 0.1, "unit": "percent", "current_value": 0.05, "status": "met"},
    {"id": "throughput", "name": "Throughput", "target": 1000, "unit": "requests/second", "current_value": 1500, "status": "met"},
]

# Feature Gates (from capabilities_api)
FEATURE_GATES = {
    "basic_transactions": {"tiers": ["free", "starter", "professional", "enterprise"]},
    "ai_categorization": {"tiers": ["starter", "professional", "enterprise"]},
    "ai_insights": {"tiers": ["professional", "enterprise"]},
    "ai_forecasting": {"tiers": ["enterprise"]},
    "plaid_integration": {"tiers": ["starter", "professional", "enterprise"]},
    "advanced_reports": {"tiers": ["professional", "enterprise"]},
    "tax_intelligence": {"tiers": ["professional", "enterprise"]},
    "compliance_automation": {"tiers": ["enterprise"]},
    "soc2_readiness": {"tiers": ["enterprise"]},
    "api_access": {"tiers": ["professional", "enterprise"]},
    "exports": {"tiers": ["starter", "professional", "enterprise"]},
}


def _get_org_info(org_id: str) -> Dict[str, Any]:
    """Get organization info from DB."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.execute(
                "SELECT name, tier, created_at FROM organizations WHERE id = ?",
                (org_id,)
            )
            row = cursor.fetchone()
            if row:
                return {
                    "name": row[0] or "Unknown",
                    "tier": row[1] or "free",
                    "created_at": row[2],
                }
    except Exception:
        pass
    return {"name": "Unknown", "tier": "free", "created_at": None}


def _calculate_error_budget(slo_target: float = 99.9, current_value: float = 99.95) -> Dict[str, Any]:
    """Calculate error budget status."""
    window_days = 30
    allowed_error_rate = 100 - slo_target
    actual_error_rate = 100 - current_value

    budget_total_minutes = (allowed_error_rate / 100) * window_days * 24 * 60
    budget_consumed_minutes = (actual_error_rate / 100) * window_days * 24 * 60
    budget_remaining_minutes = max(0, budget_total_minutes - budget_consumed_minutes)
    budget_remaining_percent = (budget_remaining_minutes / budget_total_minutes * 100) if budget_total_minutes > 0 else 100

    return {
        "budget_total_minutes": round(budget_total_minutes, 2),
        "budget_consumed_minutes": round(budget_consumed_minutes, 2),
        "budget_remaining_minutes": round(budget_remaining_minutes, 2),
        "budget_remaining_percent": round(budget_remaining_percent, 1),
        "status": "healthy" if budget_remaining_percent > 20 else "warning" if budget_remaining_percent > 0 else "exhausted",
    }


def _get_activation_metrics(org_id: str) -> Dict[str, Any]:
    """Get activation metrics for an organization."""
    metrics = {
        "time_to_first_bank": None,
        "time_to_first_classification": None,
        "time_to_first_insight": None,
        "milestones_completed": 0,
        "milestones_total": 3,
    }

    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.execute(
                "SELECT created_at FROM organizations WHERE id = ?",
                (org_id,)
            )
            row = cursor.fetchone()
            if row and row[0]:
                # Check for activation events in audit log
                events = ["PLAID_LINK_CREATED", "TRANSACTION_CLASSIFIED", "INSIGHT_GENERATED"]
                completed = 0
                for event in events:
                    cursor = conn.execute(
                        "SELECT COUNT(*) FROM audit_log WHERE metadata LIKE ? AND action = ?",
                        (f'%"org_id": "{org_id}"%', event)
                    )
                    if cursor.fetchone()[0] > 0:
                        completed += 1
                metrics["milestones_completed"] = completed
    except Exception:
        pass

    return metrics


def _get_capability_coverage() -> Dict[str, Any]:
    """Calculate capability coverage by tier."""
    tiers = ["free", "starter", "professional", "enterprise"]
    coverage = {}

    total_features = len(FEATURE_GATES)

    for tier in tiers:
        enabled = sum(1 for f, config in FEATURE_GATES.items() if tier in config["tiers"])
        coverage[tier] = {
            "enabled_count": enabled,
            "total_count": total_features,
            "coverage_percent": round((enabled / total_features) * 100, 1),
        }

    return coverage


def _build_narrative_data(org_id: str, user_id: str) -> Dict[str, Any]:
    """Build the complete narrative data structure."""
    org_info = _get_org_info(org_id)
    error_budget = _calculate_error_budget()
    activation = _get_activation_metrics(org_id)
    capability_coverage = _get_capability_coverage()

    # SLO summary
    slos_met = sum(1 for s in SLOS if s["status"] == "met")

    return {
        "organization": {
            "id": org_id,
            "name": org_info["name"],
            "tier": org_info["tier"],
            "created_at": org_info["created_at"],
        },
        "platform_status": {
            "status": "operational",
            "last_incident": None,
            "uptime_30d_percent": 99.95,
        },
        "slos": {
            "summary": {
                "total": len(SLOS),
                "met": slos_met,
                "at_risk": len(SLOS) - slos_met,
            },
            "details": SLOS,
        },
        "error_budget": error_budget,
        "activation_metrics": activation,
        "capability_coverage": capability_coverage,
    }


@router.get("/json")
async def export_json(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    GET /api/investor/export/json

    Export investor narrative as JSON snapshot (machine-readable).

    STEP 18 Hardening:
    - Rate limited (10 requests per minute per org)
    - Allowlist-based field selection
    - PII redaction enforced
    - Size cap enforced

    STEP 24 Kill-Switch:
    - Guarded by investor_exports kill-switch
    - FAIL CLOSED if disabled

    Read-only endpoint - manual trigger only.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # STEP 24: Kill-switch check (FAIL CLOSED)
    guard_feature_killswitch("investor_exports", request_id)

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    # STEP 18: Rate limit check
    _check_rate_limit(org_id, request_id)

    # Build narrative data
    narrative = _build_narrative_data(org_id, user_id)

    # STEP 18: Apply allowlist filtering (defense in depth)
    narrative = _apply_allowlist(narrative)

    # STEP 18: Redact any remaining PII
    narrative = _redact_pii(narrative)

    generated_at = datetime.utcnow().isoformat()

    response_data = {
        "request_id": request_id,
        "export_type": "json",
        "export_format": "application/json",
        "generated_at": generated_at,
        "classification": "INTERNAL / INVESTOR SNAPSHOT",
        "narrative": narrative,
        "hardening": {
            "pii_redacted": True,
            "allowlist_applied": True,
            "rate_limited": True,
        },
    }

    # STEP 18: Size cap check
    response_json = json.dumps(response_data)
    if len(response_json) > MAX_RESPONSE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail={
                "error": "response_too_large",
                "message": f"Response exceeds maximum size of {MAX_RESPONSE_SIZE_BYTES} bytes",
                "request_id": request_id,
            }
        )

    return response_data


@router.get("/pdf")
async def export_pdf(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    GET /api/investor/export/pdf

    Export investor narrative as PDF snapshot (human-readable).

    STEP 18 Hardening:
    - Rate limited (10 requests per minute per org)
    - Watermark: "INTERNAL / INVESTOR SNAPSHOT"
    - Generation timestamp included
    - PII redacted (org name not included)

    STEP 24 Kill-Switch:
    - Guarded by investor_exports kill-switch
    - FAIL CLOSED if disabled

    Returns a simple text-based PDF representation.
    Read-only endpoint - manual trigger only.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # STEP 24: Kill-switch check (FAIL CLOSED)
    guard_feature_killswitch("investor_exports", request_id)

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    # STEP 18: Rate limit check
    _check_rate_limit(org_id, request_id)

    # Build narrative data
    narrative = _build_narrative_data(org_id, user_id)

    # STEP 18: Apply allowlist and redaction
    narrative = _apply_allowlist(narrative)
    narrative = _redact_pii(narrative)

    # Generate simple text-based PDF content with STEP 18 watermark
    generated_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    # STEP 18: Watermark text
    watermark = "INTERNAL / INVESTOR SNAPSHOT"

    # Get safe values (PII redacted - no org name)
    org_tier = narrative.get('organization', {}).get('tier', 'N/A')
    platform_status = narrative.get('platform_status', {}).get('status', 'N/A')
    uptime = narrative.get('platform_status', {}).get('uptime_30d_percent', 'N/A')
    slos_total = narrative.get('slos', {}).get('summary', {}).get('total', 'N/A')
    slos_met = narrative.get('slos', {}).get('summary', {}).get('met', 'N/A')
    slos_at_risk = narrative.get('slos', {}).get('summary', {}).get('at_risk', 'N/A')
    error_status = narrative.get('error_budget', {}).get('status', 'N/A')
    error_remaining = narrative.get('error_budget', {}).get('budget_remaining_percent', 'N/A')
    milestones_completed = narrative.get('activation_metrics', {}).get('milestones_completed', 'N/A')
    milestones_total = narrative.get('activation_metrics', {}).get('milestones_total', 'N/A')

    pdf_content = f"""
%PDF-1.4
1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj
2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj
3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj
4 0 obj << /Length 2000 >>
stream
BT
/F1 12 Tf
0.7 0.7 0.7 rg
150 400 Td
45 Tz
({watermark}) Tj
0 0 0 rg
100 Tz
/F1 16 Tf
50 750 Td
(ReconAI Investor Narrative Report) Tj
/F1 8 Tf
0 -15 Td
({watermark}) Tj
/F1 10 Tf
0 -20 Td
(Generated: {generated_at}) Tj
0 -15 Td
(Request ID: {request_id}) Tj
0 -30 Td
/F1 12 Tf
(Organization Tier: {org_tier}) Tj
0 -30 Td
/F1 14 Tf
(Platform Status) Tj
/F1 10 Tf
0 -20 Td
(Status: {platform_status}) Tj
0 -15 Td
(30-Day Uptime: {uptime}%) Tj
0 -30 Td
/F1 14 Tf
(SLO Summary) Tj
/F1 10 Tf
0 -20 Td
(Total SLOs: {slos_total}) Tj
0 -15 Td
(Met: {slos_met}) Tj
0 -15 Td
(At Risk: {slos_at_risk}) Tj
0 -30 Td
/F1 14 Tf
(Error Budget) Tj
/F1 10 Tf
0 -20 Td
(Status: {error_status}) Tj
0 -15 Td
(Remaining: {error_remaining}%) Tj
0 -30 Td
/F1 14 Tf
(Activation Progress) Tj
/F1 10 Tf
0 -20 Td
(Milestones Completed: {milestones_completed}/{milestones_total}) Tj
0 -40 Td
/F1 8 Tf
0.5 0.5 0.5 rg
(This document is classified: {watermark}) Tj
0 -12 Td
(PII has been redacted. Rate limits enforced.) Tj
ET
endstream
endobj
5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj
xref
0 6
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000266 00000 n
0000002320 00000 n
trailer << /Size 6 /Root 1 0 R >>
startxref
2397
%%EOF
"""

    return Response(
        content=pdf_content.encode('latin-1'),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=reconai-investor-report-{request_id[:8]}.pdf",
            "X-Request-ID": request_id,
            "X-Classification": watermark,
            "X-Generated-At": generated_at,
        }
    )


@router.get("/status")
async def export_status(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    GET /api/investor/export/status

    Get export capability status including STEP 18 hardening info.

    Read-only endpoint.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    # STEP 18: Calculate rate limit status
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW_SECONDS
    recent_requests = len([
        ts for ts in _rate_limit_cache.get(org_id, []) if ts > window_start
    ])
    remaining_requests = max(0, RATE_LIMIT_MAX_REQUESTS - recent_requests)

    return {
        "request_id": request_id,
        "org_id": org_id,
        "export_formats": ["json", "pdf"],
        "available": True,
        "last_export": None,
        "timestamp": datetime.utcnow().isoformat(),
        "hardening": {
            "rate_limit": {
                "max_requests": RATE_LIMIT_MAX_REQUESTS,
                "window_seconds": RATE_LIMIT_WINDOW_SECONDS,
                "remaining": remaining_requests,
            },
            "max_response_size_bytes": MAX_RESPONSE_SIZE_BYTES,
            "pii_redaction": True,
            "allowlist_filtering": True,
            "pdf_watermark": "INTERNAL / INVESTOR SNAPSHOT",
        },
    }
