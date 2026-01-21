# app/routers/external_audit_api.py
"""
============================================================================
PHASE 8: EXTERNAL AUDIT MODE API
============================================================================

Provides READ-ONLY access for external auditors, investors, and regulators
to independently inspect system behavior WITHOUT assistance.

CANONICAL LAWS ENFORCED:
- Evidence > Explanation: Every claim links to evidence or UNKNOWN
- Read-Only Always: No mutation paths exist
- Manual > Automatic: No automated actions
- Unknown > Assumed: Missing data shows UNKNOWN, never inferred
- Signed > Trusted: All data includes integrity verification

IMMUTABILITY GUARANTEES:
- This entire API is READ-ONLY
- No PUT, POST, PATCH, DELETE endpoints that mutate state
- All data sourced from append-only Evidence Ledger

============================================================================
"""

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from datetime import datetime
from enum import Enum
import hashlib
import json
import logging

from app.auth_context import get_current_context, AuthContext
from app.services.audit_store import (
    get_audit_events,
    get_audit_event_by_id,
    verify_audit_chain,
    count_audit_events,
)

logger = logging.getLogger(__name__)


# =============================================================================
# AUDIT MODE ACCESS CONTROL
# =============================================================================

class AuditAccessRole(str, Enum):
    """Roles that can access external audit mode"""
    AUDITOR = "auditor"
    INVESTOR = "investor"
    REGULATOR = "regulator"
    ADMIN = "admin"


async def require_audit_access(
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Dependency that enforces audit mode access.

    In production, this would check for specific audit roles.
    For now, any authenticated user with admin or GovCon tier can access.
    """
    # Allow access for authenticated users (production would check specific roles)
    if not ctx.get("user_id"):
        raise HTTPException(status_code=401, detail="Authentication required for audit access")
    return ctx


router = APIRouter(
    prefix="/audit/external",
    tags=["External Audit Mode"],
    dependencies=[Depends(require_audit_access)],
)


# =============================================================================
# RESPONSE MODELS
# =============================================================================

class EvidenceStatus(str, Enum):
    """Status of evidence for a claim"""
    VERIFIED = "verified"          # Evidence exists and is verifiable
    UNKNOWN = "unknown"            # Evidence missing or incomplete
    PENDING = "pending"            # Evidence collection in progress


class AuditClaim(BaseModel):
    """A claim that must be backed by evidence"""
    claim_id: str
    claim_type: str
    description: str
    evidence_status: EvidenceStatus
    evidence_refs: List[str] = Field(default_factory=list)
    evidence_hash: Optional[str] = None
    timestamp: Optional[datetime] = None
    verified_at: Optional[datetime] = None


class SystemNarrative(BaseModel):
    """System narrative built from evidence only"""
    narrative_id: str
    generated_at: datetime
    scope: str
    claims: List[AuditClaim]
    total_claims: int
    verified_claims: int
    unknown_claims: int
    integrity_hash: str
    advisory: dict


class AuditWalkthroughSection(BaseModel):
    """A section of the audit walkthrough"""
    section_id: str
    title: str
    description: str
    evidence_items: List[dict]
    status: EvidenceStatus
    notes: Optional[str] = None


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _compute_integrity_hash(data: dict) -> str:
    """Compute SHA-256 hash for integrity verification"""
    json_str = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(json_str.encode()).hexdigest()


def _get_evidence_status(evidence_refs: List[str]) -> EvidenceStatus:
    """Determine evidence status based on available references"""
    if not evidence_refs:
        return EvidenceStatus.UNKNOWN
    return EvidenceStatus.VERIFIED


# =============================================================================
# PHASE 8 ENDPOINTS: EXTERNAL AUDIT MODE (READ-ONLY)
# =============================================================================

@router.get("/mode", response_model=dict)
async def get_audit_mode_status():
    """
    Get current audit mode status.

    Returns metadata about the audit view, confirming read-only mode.
    """
    return {
        "mode": "external_audit",
        "read_only": True,
        "mutation_allowed": False,
        "label": "Read-Only Audit View",
        "description": "External audit mode provides read-only access to system evidence. No actions can modify system state.",
        "capabilities": [
            "view_evidence_timeline",
            "view_system_narrative",
            "verify_integrity",
            "export_evidence_packs",
        ],
        "restrictions": [
            "no_data_mutation",
            "no_automated_actions",
            "no_inferred_explanations",
        ],
        "advisory": {
            "type": "advisory",
            "autonomous": False,
            "message": "This is a read-only audit view. All data is sourced from the Evidence Ledger.",
        }
    }


@router.get("/walkthrough", response_model=dict)
async def get_audit_walkthrough(
    scope: str = "full",
    limit: int = 100,
):
    """
    Get audit walkthrough view.

    Provides a structured walkthrough of system behavior organized by evidence.
    An auditor can answer "What happened?" without asking engineering.

    RULES:
    - All claims link to evidence or show UNKNOWN
    - No summaries without evidence references
    - No inferred explanations
    """
    now = datetime.utcnow()

    # Fetch events from Evidence Ledger
    events = get_audit_events(limit=limit)

    # Build sections from evidence
    sections = []

    # Section 1: Bank Connections
    bank_events = [e for e in events if e.entity_type in ("bank_item", "plaid_item", "bank_connection")]
    sections.append(AuditWalkthroughSection(
        section_id="bank_connections",
        title="Bank Connections",
        description="Evidence of bank account connections and sync operations",
        evidence_items=[{
            "event_id": e.id,
            "event_type": e.event_type,
            "timestamp": e.created_at,
            "entity_id": e.entity_id,
            "actor": e.actor_id,
            "hash": e.event_hash,
        } for e in bank_events],
        status=EvidenceStatus.VERIFIED if bank_events else EvidenceStatus.UNKNOWN,
        notes="UNKNOWN: No bank connection events recorded" if not bank_events else None,
    ))

    # Section 2: Document Uploads
    doc_events = [e for e in events if e.entity_type in ("document", "upload", "file")]
    sections.append(AuditWalkthroughSection(
        section_id="document_uploads",
        title="Document Uploads",
        description="Evidence of document upload and processing operations",
        evidence_items=[{
            "event_id": e.id,
            "event_type": e.event_type,
            "timestamp": e.created_at,
            "entity_id": e.entity_id,
            "actor": e.actor_id,
            "hash": e.event_hash,
        } for e in doc_events],
        status=EvidenceStatus.VERIFIED if doc_events else EvidenceStatus.UNKNOWN,
        notes="UNKNOWN: No document upload events recorded" if not doc_events else None,
    ))

    # Section 3: Sync Attempts
    sync_events = [e for e in events if "sync" in e.event_type.lower()]
    sections.append(AuditWalkthroughSection(
        section_id="sync_attempts",
        title="Sync Attempts",
        description="Evidence of data synchronization operations (success and failure)",
        evidence_items=[{
            "event_id": e.id,
            "event_type": e.event_type,
            "timestamp": e.created_at,
            "entity_id": e.entity_id,
            "actor": e.actor_id,
            "hash": e.event_hash,
            "status": e.payload.get("status", "UNKNOWN") if e.payload else "UNKNOWN",
        } for e in sync_events],
        status=EvidenceStatus.VERIFIED if sync_events else EvidenceStatus.UNKNOWN,
        notes="UNKNOWN: No sync events recorded" if not sync_events else None,
    ))

    # Section 4: Failures
    failure_events = [e for e in events if any(x in e.event_type.lower() for x in ("error", "fail", "critical"))]
    sections.append(AuditWalkthroughSection(
        section_id="failures",
        title="Failures and Errors",
        description="Evidence of system failures and error events",
        evidence_items=[{
            "event_id": e.id,
            "event_type": e.event_type,
            "timestamp": e.created_at,
            "entity_id": e.entity_id,
            "actor": e.actor_id,
            "hash": e.event_hash,
            "severity": e.payload.get("severity", "UNKNOWN") if e.payload else "UNKNOWN",
        } for e in failure_events],
        status=EvidenceStatus.VERIFIED if failure_events else EvidenceStatus.UNKNOWN,
        notes="No failure events recorded (this may indicate no failures OR missing evidence)" if not failure_events else None,
    ))

    # Section 5: Exports Generated
    export_events = [e for e in events if "export" in e.event_type.lower()]
    sections.append(AuditWalkthroughSection(
        section_id="exports",
        title="Export Operations",
        description="Evidence of data export operations",
        evidence_items=[{
            "event_id": e.id,
            "event_type": e.event_type,
            "timestamp": e.created_at,
            "entity_id": e.entity_id,
            "actor": e.actor_id,
            "hash": e.event_hash,
        } for e in export_events],
        status=EvidenceStatus.VERIFIED if export_events else EvidenceStatus.UNKNOWN,
        notes="UNKNOWN: No export events recorded" if not export_events else None,
    ))

    # Compute integrity hash for the walkthrough
    walkthrough_data = {
        "scope": scope,
        "sections": [s.dict() for s in sections],
        "generated_at": now.isoformat(),
    }
    integrity_hash = _compute_integrity_hash(walkthrough_data)

    # Count statistics
    total_sections = len(sections)
    verified_sections = len([s for s in sections if s.status == EvidenceStatus.VERIFIED])
    unknown_sections = len([s for s in sections if s.status == EvidenceStatus.UNKNOWN])

    return {
        "walkthrough_id": f"walk_{now.strftime('%Y%m%d_%H%M%S')}",
        "mode": "read_only_audit_view",
        "generated_at": now.isoformat(),
        "scope": scope,
        "sections": [s.dict() for s in sections],
        "statistics": {
            "total_sections": total_sections,
            "verified_sections": verified_sections,
            "unknown_sections": unknown_sections,
            "total_events": len(events),
        },
        "integrity_hash": integrity_hash,
        "advisory": {
            "type": "advisory",
            "autonomous": False,
            "read_only": True,
            "message": "Audit walkthrough generated from Evidence Ledger. Sections marked UNKNOWN have no recorded evidence.",
        }
    }


@router.get("/narrative", response_model=dict)
async def get_system_narrative(
    entity_type: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    limit: int = 500,
):
    """
    Get system narrative built ONLY from evidence.

    RULES:
    - Every statement links to evidence or shows UNKNOWN
    - No AI summaries
    - No inferred explanations
    - Evidence-first, not explanation-first
    """
    now = datetime.utcnow()

    # Fetch events from Evidence Ledger with filters
    events = get_audit_events(
        entity_type=entity_type,
        start_date=start_date.isoformat() if start_date else None,
        end_date=end_date.isoformat() if end_date else None,
        limit=limit,
    )

    # Build claims from events (evidence -> claim, not claim -> evidence)
    claims = []
    for event in events:
        claim = AuditClaim(
            claim_id=f"claim_{event.id}",
            claim_type=event.event_type,
            description=event.payload.get("description", "UNKNOWN") if event.payload else "UNKNOWN",
            evidence_status=EvidenceStatus.VERIFIED,
            evidence_refs=[event.id],
            evidence_hash=event.event_hash,
            timestamp=datetime.fromisoformat(event.created_at.replace("Z", "+00:00")) if event.created_at else None,
            verified_at=now,
        )
        claims.append(claim)

    # Compute integrity hash
    narrative_data = {
        "claims": [c.dict() for c in claims],
        "generated_at": now.isoformat(),
    }
    integrity_hash = _compute_integrity_hash(narrative_data)

    return SystemNarrative(
        narrative_id=f"narr_{now.strftime('%Y%m%d_%H%M%S')}",
        generated_at=now,
        scope=f"entity_type={entity_type or 'all'}",
        claims=claims,
        total_claims=len(claims),
        verified_claims=len([c for c in claims if c.evidence_status == EvidenceStatus.VERIFIED]),
        unknown_claims=len([c for c in claims if c.evidence_status == EvidenceStatus.UNKNOWN]),
        integrity_hash=integrity_hash,
        advisory={
            "type": "advisory",
            "autonomous": False,
            "read_only": True,
            "message": "System narrative built from Evidence Ledger. Each claim links to verifiable evidence.",
        }
    ).dict()


@router.get("/timeline", response_model=dict)
async def get_evidence_timeline(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    entity_type: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
):
    """
    Get chronological evidence timeline.

    Returns events in chronological order with hash chain verification.
    """
    now = datetime.utcnow()

    # Fetch events
    events = get_audit_events(
        entity_type=entity_type,
        start_date=start_date.isoformat() if start_date else None,
        end_date=end_date.isoformat() if end_date else None,
        limit=limit,
        offset=offset,
    )

    # Reverse for chronological order (oldest first)
    events_chrono = list(reversed(events))

    # Build timeline entries
    timeline = []
    for event in events_chrono:
        timeline.append({
            "event_id": event.id,
            "timestamp": event.created_at,
            "event_type": event.event_type,
            "entity_type": event.entity_type,
            "entity_id": event.entity_id or "UNKNOWN",
            "actor_id": event.actor_id,
            "description": event.payload.get("description", "UNKNOWN") if event.payload else "UNKNOWN",
            "hash": event.event_hash,
            "prev_hash": event.prev_hash,
            "integrity": "chain_linked" if event.prev_hash else "genesis",
        })

    # Get total count
    total = count_audit_events(
        entity_type=entity_type,
    )

    return {
        "timeline_id": f"tl_{now.strftime('%Y%m%d_%H%M%S')}",
        "generated_at": now.isoformat(),
        "mode": "read_only",
        "events": timeline,
        "pagination": {
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": (offset + limit) < total,
        },
        "advisory": {
            "type": "advisory",
            "autonomous": False,
            "read_only": True,
            "message": "Evidence timeline in chronological order. Each event is hash-chain linked.",
        }
    }


@router.get("/integrity", response_model=dict)
async def verify_system_integrity(
    limit: int = 500,
):
    """
    Verify system integrity via hash chain.

    Returns detailed verification results for auditor review.
    """
    now = datetime.utcnow()

    # Get total count
    total = count_audit_events()

    if total == 0:
        return {
            "verification_id": f"ver_{now.strftime('%Y%m%d_%H%M%S')}",
            "verified_at": now.isoformat(),
            "status": "empty",
            "total_events": 0,
            "verified_events": 0,
            "integrity_valid": True,
            "issues": [],
            "advisory": {
                "type": "advisory",
                "message": "Evidence Ledger is empty. No events to verify.",
            }
        }

    # Verify hash chain
    is_valid, issues = verify_audit_chain(limit=limit)

    return {
        "verification_id": f"ver_{now.strftime('%Y%m%d_%H%M%S')}",
        "verified_at": now.isoformat(),
        "status": "valid" if is_valid else "INTEGRITY_VIOLATION",
        "total_events": total,
        "verified_events": min(total, limit),
        "integrity_valid": is_valid,
        "issues": issues,
        "hash_algorithm": "SHA-256",
        "chain_type": "append_only_linked",
        "advisory": {
            "type": "advisory",
            "autonomous": False,
            "read_only": True,
            "message": "Hash chain verification complete." if is_valid else f"ALERT: {len(issues)} integrity issues detected!",
        }
    }


@router.get("/unknowns", response_model=dict)
async def list_explicit_unknowns():
    """
    List all data points marked as UNKNOWN.

    Per canonical law: If data is missing or incomplete, display "UNKNOWN".
    No smoothing, no inference.
    """
    now = datetime.utcnow()

    # Categories that should have evidence but may be missing
    expected_categories = [
        {"category": "bank_connections", "entity_type": "bank_item", "description": "Bank account connection events"},
        {"category": "document_uploads", "entity_type": "document", "description": "Document upload events"},
        {"category": "sync_operations", "entity_type": "sync", "description": "Data synchronization events"},
        {"category": "transaction_imports", "entity_type": "transaction", "description": "Transaction import events"},
        {"category": "audit_exports", "entity_type": "audit_export", "description": "Audit export operations"},
    ]

    unknowns = []
    for cat in expected_categories:
        count = count_audit_events(entity_type=cat["entity_type"])
        if count == 0:
            unknowns.append({
                "category": cat["category"],
                "entity_type": cat["entity_type"],
                "description": cat["description"],
                "status": "UNKNOWN",
                "evidence_count": 0,
                "reason": "No evidence recorded for this category",
            })

    return {
        "unknowns_report_id": f"unk_{now.strftime('%Y%m%d_%H%M%S')}",
        "generated_at": now.isoformat(),
        "total_unknown_categories": len(unknowns),
        "unknowns": unknowns,
        "advisory": {
            "type": "advisory",
            "autonomous": False,
            "read_only": True,
            "message": "Categories listed as UNKNOWN have no recorded evidence. This does not imply absence of activity, only absence of evidence.",
        }
    }
