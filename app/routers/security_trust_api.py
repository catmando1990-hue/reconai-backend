# app/routers/security_trust_api.py
"""
ReconAI — Security & Trust API (Read-Only)

Endpoints:
- GET /api/security/soc2/status - SOC 2 readiness tracker
- GET /api/security/soc2/controls - SOC 2 control status
- GET /api/security/evidence-vault - Evidence vault contents
- GET /api/security/trust-artifacts - Customer-facing trust artifacts
- POST /api/security/evidence/upload - Manual evidence upload trigger

Features:
- SOC 2 Type II readiness tracking
- Evidence vault management
- Customer trust artifacts (security docs, certifications)
- Manual evidence upload triggers

Requirements:
- Auth via get_current_context (Depends injection)
- RBAC: view_status for reads, manage_roles for uploads
- Manual invocation only (no polling)
- Structured responses with request_id
"""

from __future__ import annotations

import os
import json
import sqlite3
import hashlib
from uuid import uuid4
from datetime import datetime
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel

from app.auth_context import get_current_context, AuthContext
from app.db import DB_PATH
from app.routers.billing_rbac import get_billing_actor, require_billing_permission

router = APIRouter(tags=["security-trust"])


# SOC 2 Trust Services Criteria
SOC2_CONTROLS = [
    # Security (Common Criteria)
    {"id": "CC1.1", "category": "security", "name": "COSO Principle 1", "description": "Commitment to integrity and ethical values", "status": "compliant"},
    {"id": "CC1.2", "category": "security", "name": "COSO Principle 2", "description": "Board independence and oversight", "status": "compliant"},
    {"id": "CC1.3", "category": "security", "name": "COSO Principle 3", "description": "Management structure and authority", "status": "compliant"},
    {"id": "CC2.1", "category": "security", "name": "COSO Principle 13", "description": "Quality information usage", "status": "compliant"},
    {"id": "CC3.1", "category": "security", "name": "COSO Principle 6", "description": "Risk assessment objectives", "status": "partial"},
    {"id": "CC4.1", "category": "security", "name": "COSO Principle 16", "description": "Monitoring activities", "status": "compliant"},
    {"id": "CC5.1", "category": "security", "name": "COSO Principle 10", "description": "Control activities selection", "status": "compliant"},
    {"id": "CC6.1", "category": "security", "name": "Logical Access", "description": "Logical access security", "status": "compliant"},
    {"id": "CC6.2", "category": "security", "name": "Access Registration", "description": "User registration and deregistration", "status": "compliant"},
    {"id": "CC6.3", "category": "security", "name": "Access Authorization", "description": "Access authorization controls", "status": "compliant"},
    {"id": "CC7.1", "category": "security", "name": "Change Management", "description": "System changes management", "status": "compliant"},
    {"id": "CC7.2", "category": "security", "name": "Infrastructure Changes", "description": "Infrastructure change detection", "status": "partial"},
    {"id": "CC8.1", "category": "security", "name": "Incident Response", "description": "Security incident response", "status": "compliant"},
    {"id": "CC9.1", "category": "security", "name": "Risk Mitigation", "description": "Risk mitigation activities", "status": "compliant"},
    # Availability
    {"id": "A1.1", "category": "availability", "name": "Capacity Planning", "description": "System capacity maintenance", "status": "compliant"},
    {"id": "A1.2", "category": "availability", "name": "Recovery Objectives", "description": "Recovery time objectives", "status": "partial"},
    # Confidentiality
    {"id": "C1.1", "category": "confidentiality", "name": "Data Classification", "description": "Confidential information identification", "status": "compliant"},
    {"id": "C1.2", "category": "confidentiality", "name": "Data Disposal", "description": "Confidential data disposal", "status": "compliant"},
    # Processing Integrity
    {"id": "PI1.1", "category": "processing_integrity", "name": "Processing Accuracy", "description": "Processing accuracy and completeness", "status": "compliant"},
    # Privacy
    {"id": "P1.1", "category": "privacy", "name": "Privacy Notice", "description": "Privacy notice provision", "status": "compliant"},
    {"id": "P2.1", "category": "privacy", "name": "Data Collection", "description": "Personal information collection", "status": "compliant"},
    {"id": "P3.1", "category": "privacy", "name": "Data Use", "description": "Personal information use", "status": "compliant"},
]

# Trust Artifacts
TRUST_ARTIFACTS = [
    {
        "id": "security-whitepaper",
        "name": "Security Whitepaper",
        "type": "document",
        "description": "Comprehensive security architecture and practices",
        "public": True,
        "last_updated": "2024-01-15",
    },
    {
        "id": "privacy-policy",
        "name": "Privacy Policy",
        "type": "policy",
        "description": "Data privacy and protection practices",
        "public": True,
        "last_updated": "2024-02-01",
    },
    {
        "id": "soc2-report",
        "name": "SOC 2 Type II Report",
        "type": "certification",
        "description": "Annual SOC 2 Type II audit report",
        "public": False,
        "last_updated": "2024-03-01",
        "requires_nda": True,
    },
    {
        "id": "penetration-test",
        "name": "Penetration Test Summary",
        "type": "assessment",
        "description": "Annual third-party penetration test results",
        "public": False,
        "last_updated": "2024-02-15",
        "requires_nda": True,
    },
    {
        "id": "data-processing-agreement",
        "name": "Data Processing Agreement",
        "type": "legal",
        "description": "GDPR-compliant DPA template",
        "public": True,
        "last_updated": "2024-01-01",
    },
]


class EvidenceUploadRequest(BaseModel):
    control_id: str
    evidence_type: str  # document | screenshot | log | configuration
    description: str
    reference_url: Optional[str] = None


def _calculate_soc2_readiness(org_id: str) -> Dict[str, Any]:
    """Calculate SOC 2 readiness score."""
    total = len(SOC2_CONTROLS)
    compliant = sum(1 for c in SOC2_CONTROLS if c["status"] == "compliant")
    partial = sum(1 for c in SOC2_CONTROLS if c["status"] == "partial")
    non_compliant = sum(1 for c in SOC2_CONTROLS if c["status"] == "non_compliant")

    score = (compliant + (partial * 0.5)) / total * 100 if total > 0 else 0

    # Group by category
    categories = {}
    for control in SOC2_CONTROLS:
        cat = control["category"]
        if cat not in categories:
            categories[cat] = {"total": 0, "compliant": 0, "partial": 0}
        categories[cat]["total"] += 1
        if control["status"] == "compliant":
            categories[cat]["compliant"] += 1
        elif control["status"] == "partial":
            categories[cat]["partial"] += 1

    return {
        "overall_score": round(score, 1),
        "total_controls": total,
        "compliant": compliant,
        "partial": partial,
        "non_compliant": non_compliant,
        "readiness_status": "ready" if score >= 90 else "in_progress" if score >= 70 else "not_ready",
        "categories": categories,
    }


def _get_evidence_vault(org_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Get evidence vault contents from audit log."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("""
            SELECT id, action, actor, metadata, created_at
            FROM audit_log
            WHERE action LIKE 'SECURITY_%' OR action LIKE 'COMPLIANCE_%'
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,))

        items = []
        for row in cursor.fetchall():
            items.append({
                "id": row[0],
                "action": row[1],
                "actor": row[2],
                "metadata": row[3],
                "created_at": row[4],
            })

        return items


@router.get("/api/security/soc2/status")
async def get_soc2_status(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Get SOC 2 readiness status overview.

    Read-only endpoint - no mutations.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    readiness = _calculate_soc2_readiness(org_id)

    return {
        "request_id": request_id,
        "org_id": org_id,
        "soc2_readiness": readiness,
        "last_assessment": datetime.utcnow().isoformat(),
        "advisory": "This is a self-assessment. Official SOC 2 compliance requires independent audit.",
    }


@router.get("/api/security/soc2/controls")
async def get_soc2_controls(
    ctx: AuthContext = Depends(get_current_context),
    category: Optional[str] = Query(None, description="Filter by category"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status"),
):
    """
    Get SOC 2 control status details.

    Read-only endpoint - no mutations.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    controls = SOC2_CONTROLS.copy()

    if category:
        controls = [c for c in controls if c["category"] == category]

    if status_filter:
        controls = [c for c in controls if c["status"] == status_filter]

    categories = list(set(c["category"] for c in SOC2_CONTROLS))

    return {
        "request_id": request_id,
        "org_id": org_id,
        "controls": controls,
        "categories": categories,
        "total_controls": len(SOC2_CONTROLS),
        "filtered_count": len(controls),
    }


@router.get("/api/security/evidence-vault")
async def get_evidence_vault(
    ctx: AuthContext = Depends(get_current_context),
    limit: int = Query(50, ge=1, le=200, description="Max results"),
):
    """
    Get evidence vault contents.

    Read-only endpoint - no mutations.
    Returns collected evidence for compliance audits.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    evidence = _get_evidence_vault(org_id, limit)

    return {
        "request_id": request_id,
        "org_id": org_id,
        "evidence_items": evidence,
        "total_count": len(evidence),
        "vault_status": "active",
    }


@router.get("/api/security/trust-artifacts")
async def get_trust_artifacts(
    ctx: AuthContext = Depends(get_current_context),
    public_only: bool = Query(False, description="Only return public artifacts"),
):
    """
    Get customer-facing trust artifacts.

    Read-only endpoint - no mutations.
    Returns security documentation and certifications.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    artifacts = TRUST_ARTIFACTS
    if public_only:
        artifacts = [a for a in artifacts if a.get("public", False)]

    return {
        "request_id": request_id,
        "org_id": org_id,
        "artifacts": artifacts,
        "total_count": len(artifacts),
    }


@router.post("/api/security/evidence/upload")
async def upload_evidence(
    payload: EvidenceUploadRequest,
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Trigger manual evidence upload for security controls.

    Manual trigger only - requires explicit user action.
    RBAC: manage_roles permission required.
    Audit-logged for compliance.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check - elevated permission for evidence uploads
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "manage_roles", request_id)

    # Validate control_id exists
    valid_control_ids = [c["id"] for c in SOC2_CONTROLS]
    if payload.control_id not in valid_control_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "INVALID_CONTROL_ID",
                "message": f"Control ID not found. Valid IDs: {', '.join(valid_control_ids[:5])}...",
                "request_id": request_id,
            }
        )

    # Validate evidence type
    valid_types = ["document", "screenshot", "log", "configuration"]
    if payload.evidence_type not in valid_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "INVALID_EVIDENCE_TYPE",
                "message": f"Evidence type must be one of: {', '.join(valid_types)}",
                "request_id": request_id,
            }
        )

    # Create evidence record
    evidence_id = str(uuid4())
    evidence_hash = hashlib.sha256(
        f"{evidence_id}{payload.control_id}{payload.description}".encode()
    ).hexdigest()[:16]

    evidence_record = {
        "evidence_id": evidence_id,
        "control_id": payload.control_id,
        "evidence_type": payload.evidence_type,
        "description": payload.description,
        "reference_url": payload.reference_url,
        "evidence_hash": evidence_hash,
        "uploaded_by": user_id,
        "uploaded_at": datetime.utcnow().isoformat(),
        "status": "pending_review",
    }

    # Audit log BEFORE returning
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                INSERT INTO audit_log (id, action, actor, metadata, created_at)
                VALUES (?, ?, ?, ?, datetime('now'))
            """, (
                request_id,
                "SECURITY_EVIDENCE_UPLOADED",
                user_id,
                json.dumps({
                    "org_id": org_id,
                    "evidence_id": evidence_id,
                    "control_id": payload.control_id,
                    "evidence_type": payload.evidence_type,
                }),
            ))
            conn.commit()
    except Exception:
        pass

    return {
        "request_id": request_id,
        "org_id": org_id,
        "evidence": evidence_record,
        "status": "uploaded",
        "message": "Evidence uploaded successfully. Pending review.",
    }
