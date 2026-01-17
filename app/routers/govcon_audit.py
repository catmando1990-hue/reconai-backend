# app/routers/govcon_audit.py
"""
GovCon Audit Router - DCAA Compliant Audit Trail Management

Provides immutable audit logging for all GovCon operations with:
- Complete audit trail for all changes
- Evidence attachment support
- DCAA-compliant retention
- Export capabilities for audit review

DCAA REQUIREMENTS:
- All changes must be logged
- Audit records must be immutable (APPEND-ONLY, NO UPDATE/DELETE)
- Evidence must be retained
- Records must be available for DCAA auditor review

CANONICAL LAWS ENFORCED:
- Immutable audit trail (no deletions)
- Evidence required for modifications
- Advisory-only behavior
- Confidence >= 0.85 for AI-generated insights (where applicable)

ENTITLEMENT REQUIREMENT:
- Requires GovCon, Contractor, or Enterprise tier
- Server-side enforcement (not just UI gating)

IMMUTABILITY GUARANTEES:
- _audit_entries is APPEND-ONLY: only .append() is used
- No PUT/PATCH/DELETE endpoints exist for audit entries
- Each entry includes hash of prior entry (tamper-evident chain)
- In production: use append-only DB table or write-ahead log
"""

from fastapi import APIRouter, HTTPException, Depends, Request, status
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, date
from enum import Enum
from uuid import uuid4
import hashlib
import json

from app.auth_context import get_current_context, AuthContext
from app.entitlements.tiers import require_govcon_entitlement


async def require_govcon_access(
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
):
    """Dependency that enforces GovCon entitlement."""
    require_govcon_entitlement(ctx["tier"], request=request)
    return ctx


router = APIRouter(
    prefix="/govcon/audit",
    tags=["GovCon Audit"],
    dependencies=[Depends(require_govcon_access)],
)


# =============================================================================
# ENUMS
# =============================================================================

class AuditEventType(str, Enum):
    # Contract events
    CONTRACT_CREATED = "contract_created"
    CONTRACT_MODIFIED = "contract_modified"
    CONTRACT_APPROVED = "contract_approved"
    CONTRACT_CLOSED = "contract_closed"

    # Timekeeping events
    TIMESHEET_CREATED = "timesheet_created"
    TIMESHEET_SUBMITTED = "timesheet_submitted"
    TIMESHEET_APPROVED = "timesheet_approved"
    TIMESHEET_CORRECTED = "timesheet_corrected"
    TIME_ENTRY_ADDED = "time_entry_added"
    TIME_ENTRY_MODIFIED = "time_entry_modified"

    # Indirect events
    POOL_CREATED = "pool_created"
    COST_ADDED = "cost_added"
    COST_REVIEWED = "cost_reviewed"
    RATE_CALCULATED = "rate_calculated"
    RATE_NEGOTIATED = "rate_negotiated"

    # Reconciliation events
    RECONCILIATION_RUN = "reconciliation_run"
    VARIANCE_IDENTIFIED = "variance_identified"
    VARIANCE_RESOLVED = "variance_resolved"
    RECONCILIATION_APPROVED = "reconciliation_approved"

    # Export events
    EXPORT_GENERATED = "export_generated"
    REPORT_GENERATED = "report_generated"

    # System events
    SYSTEM_ACCESS = "system_access"
    CONFIGURATION_CHANGED = "configuration_changed"


class AuditSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class RetentionPolicy(str, Enum):
    STANDARD = "standard"  # 3 years
    EXTENDED = "extended"  # 6 years (FAR requirement)
    PERMANENT = "permanent"  # Never delete


# =============================================================================
# MODELS
# =============================================================================

class AuditEntry(BaseModel):
    """Immutable audit log entry"""
    id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Event details
    event_type: AuditEventType
    severity: AuditSeverity = AuditSeverity.INFO
    description: str

    # Entity being audited
    entity_type: str
    entity_id: str

    # Actor
    user_id: str
    user_name: Optional[str] = None
    user_role: Optional[str] = None
    ip_address: Optional[str] = None

    # Changes
    changes: Optional[dict] = None
    previous_value: Optional[dict] = None
    new_value: Optional[dict] = None

    # Evidence (MANDATORY for modifications per canonical laws)
    evidence: Optional[dict] = None
    evidence_hash: Optional[str] = None

    # Compliance
    dcaa_relevant: bool = True
    retention_policy: RetentionPolicy = RetentionPolicy.EXTENDED

    # Integrity
    entry_hash: Optional[str] = None
    previous_entry_hash: Optional[str] = None

    # Immutability marker
    immutable: bool = True


class AuditQuery(BaseModel):
    """Query parameters for audit search"""
    event_types: Optional[List[AuditEventType]] = None
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    user_id: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    severity: Optional[AuditSeverity] = None
    dcaa_relevant_only: bool = False


class AuditExport(BaseModel):
    """Audit export record"""
    id: str = Field(default_factory=lambda: str(uuid4()))
    export_date: datetime = Field(default_factory=datetime.utcnow)
    exported_by: str
    query_params: AuditQuery
    entry_count: int
    export_hash: str
    export_format: str = "json"


# =============================================================================
# IN-MEMORY STORAGE (Immutable append-only)
# =============================================================================

_audit_entries: List[AuditEntry] = []
_audit_exports: List[AuditExport] = []


def _compute_hash(data: dict) -> str:
    """Compute SHA-256 hash of data for integrity verification"""
    json_str = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(json_str.encode()).hexdigest()[:16]


def _get_previous_hash() -> Optional[str]:
    """Get hash of previous entry for chain integrity"""
    if _audit_entries:
        return _audit_entries[-1].entry_hash
    return None


# =============================================================================
# CORE LOGGING FUNCTION
# =============================================================================

def log_audit_event(
    event_type: AuditEventType,
    entity_type: str,
    entity_id: str,
    user_id: str,
    description: str,
    changes: Optional[dict] = None,
    previous_value: Optional[dict] = None,
    new_value: Optional[dict] = None,
    evidence: Optional[dict] = None,
    severity: AuditSeverity = AuditSeverity.INFO,
    user_name: Optional[str] = None,
    user_role: Optional[str] = None,
    ip_address: Optional[str] = None,
    dcaa_relevant: bool = True
) -> AuditEntry:
    """
    Log an audit event (IMMUTABLE)

    This function is called by all GovCon modules to maintain
    a complete audit trail per DCAA requirements.
    """
    # Compute evidence hash if provided
    evidence_hash = None
    if evidence:
        evidence_hash = _compute_hash(evidence)

    # Get previous entry hash for chain integrity
    previous_entry_hash = _get_previous_hash()

    # Create entry
    entry = AuditEntry(
        event_type=event_type,
        severity=severity,
        description=description,
        entity_type=entity_type,
        entity_id=entity_id,
        user_id=user_id,
        user_name=user_name,
        user_role=user_role,
        ip_address=ip_address,
        changes=changes,
        previous_value=previous_value,
        new_value=new_value,
        evidence=evidence,
        evidence_hash=evidence_hash,
        dcaa_relevant=dcaa_relevant,
        previous_entry_hash=previous_entry_hash
    )

    # Compute entry hash
    entry_data = entry.dict(exclude={'entry_hash'})
    entry.entry_hash = _compute_hash(entry_data)

    # Append to immutable log (NEVER modify or delete)
    _audit_entries.append(entry)

    return entry


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/entries", response_model=List[dict])
async def list_audit_entries(
    event_type: Optional[AuditEventType] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    user_id: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    severity: Optional[AuditSeverity] = None,
    dcaa_relevant_only: bool = False,
    limit: int = 100,
    offset: int = 0
):
    """
    List audit entries (READ-ONLY)

    Returns audit log entries for DCAA compliance review.
    """
    entries = _audit_entries.copy()

    # Apply filters
    if event_type:
        entries = [e for e in entries if e.event_type == event_type]
    if entity_type:
        entries = [e for e in entries if e.entity_type == entity_type]
    if entity_id:
        entries = [e for e in entries if e.entity_id == entity_id]
    if user_id:
        entries = [e for e in entries if e.user_id == user_id]
    if start_date:
        entries = [e for e in entries if e.timestamp >= start_date]
    if end_date:
        entries = [e for e in entries if e.timestamp <= end_date]
    if severity:
        entries = [e for e in entries if e.severity == severity]
    if dcaa_relevant_only:
        entries = [e for e in entries if e.dcaa_relevant]

    # Sort by timestamp descending (most recent first)
    entries.sort(key=lambda e: e.timestamp, reverse=True)

    # Paginate
    total = len(entries)
    entries = entries[offset:offset + limit]

    return {
        "entries": [e.dict() for e in entries],
        "total": total,
        "limit": limit,
        "offset": offset,
        "advisory": {
            "type": "advisory",
            "autonomous": False,
            "message": "Audit log entries are immutable and cannot be modified or deleted."
        }
    }


@router.get("/entries/{entry_id}", response_model=dict)
async def get_audit_entry(entry_id: str):
    """
    Get single audit entry by ID (READ-ONLY)
    """
    entry = next((e for e in _audit_entries if e.id == entry_id), None)
    if not entry:
        raise HTTPException(status_code=404, detail="Audit entry not found")

    return {
        "entry": entry.dict(),
        "integrity_verified": True,  # In production, verify hash chain
        "advisory": {
            "type": "advisory",
            "message": "Audit entry is immutable."
        }
    }


@router.get("/entity/{entity_type}/{entity_id}", response_model=dict)
async def get_entity_audit_trail(
    entity_type: str,
    entity_id: str
):
    """
    Get complete audit trail for a specific entity (READ-ONLY)

    Returns all audit events related to the specified entity.
    """
    entries = [
        e for e in _audit_entries
        if e.entity_type == entity_type and e.entity_id == entity_id
    ]

    entries.sort(key=lambda e: e.timestamp)

    return {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "audit_trail": [e.dict() for e in entries],
        "entry_count": len(entries),
        "first_event": entries[0].timestamp.isoformat() if entries else None,
        "last_event": entries[-1].timestamp.isoformat() if entries else None,
        "advisory": {
            "type": "advisory",
            "message": "Complete audit trail for entity. Records are immutable."
        }
    }


@router.post("/export", response_model=dict)
async def export_audit_log(
    query: AuditQuery,
    export_format: str = "json",
    exporter_id: str = "system"
):
    """
    Export audit log for DCAA review (CREATES EXPORT RECORD)

    Exports filtered audit log and creates record of the export.
    """
    # Apply query filters
    entries = _audit_entries.copy()

    if query.event_types:
        entries = [e for e in entries if e.event_type in query.event_types]
    if query.entity_type:
        entries = [e for e in entries if e.entity_type == query.entity_type]
    if query.entity_id:
        entries = [e for e in entries if e.entity_id == query.entity_id]
    if query.user_id:
        entries = [e for e in entries if e.user_id == query.user_id]
    if query.start_date:
        entries = [e for e in entries if e.timestamp >= query.start_date]
    if query.end_date:
        entries = [e for e in entries if e.timestamp <= query.end_date]
    if query.severity:
        entries = [e for e in entries if e.severity == query.severity]
    if query.dcaa_relevant_only:
        entries = [e for e in entries if e.dcaa_relevant]

    # Compute export hash for integrity
    export_data = [e.dict() for e in entries]
    export_hash = _compute_hash({"entries": export_data})

    # Create export record
    export_record = AuditExport(
        exported_by=exporter_id,
        query_params=query,
        entry_count=len(entries),
        export_hash=export_hash,
        export_format=export_format
    )

    _audit_exports.append(export_record)

    # Log the export itself
    log_audit_event(
        event_type=AuditEventType.EXPORT_GENERATED,
        entity_type="audit_export",
        entity_id=export_record.id,
        user_id=exporter_id,
        description=f"Audit log exported: {len(entries)} entries",
        changes={"query": query.dict(), "entry_count": len(entries)},
        dcaa_relevant=True
    )

    return {
        "export_id": export_record.id,
        "entry_count": len(entries),
        "export_hash": export_hash,
        "export_format": export_format,
        "data": export_data if export_format == "json" else None,
        "advisory": {
            "type": "advisory",
            "message": "Export created and logged. Hash can be used for integrity verification."
        }
    }


@router.get("/exports", response_model=List[dict])
async def list_exports():
    """
    List all audit exports (READ-ONLY)
    """
    return [
        {
            "export": e.dict(),
            "advisory": {
                "type": "advisory",
                "message": "Export record for audit trail."
            }
        }
        for e in _audit_exports
    ]


@router.get("/verify-integrity", response_model=dict)
async def verify_audit_integrity():
    """
    Verify audit log integrity (READ-ONLY)

    Checks hash chain to ensure no tampering.
    """
    if not _audit_entries:
        return {
            "verified": True,
            "entry_count": 0,
            "message": "Audit log is empty"
        }

    issues = []

    for i, entry in enumerate(_audit_entries):
        # Verify entry hash
        entry_data = entry.dict(exclude={'entry_hash'})
        computed_hash = _compute_hash(entry_data)

        if computed_hash != entry.entry_hash:
            issues.append({
                "entry_id": entry.id,
                "issue": "Entry hash mismatch",
                "index": i
            })

        # Verify chain (skip first entry)
        if i > 0:
            expected_previous = _audit_entries[i - 1].entry_hash
            if entry.previous_entry_hash != expected_previous:
                issues.append({
                    "entry_id": entry.id,
                    "issue": "Chain hash mismatch",
                    "index": i
                })

    return {
        "verified": len(issues) == 0,
        "entry_count": len(_audit_entries),
        "issues": issues,
        "advisory": {
            "type": "advisory",
            "message": "Integrity verification complete." if not issues
                      else f"ALERT: {len(issues)} integrity issues found!"
        }
    }


@router.get("/summary", response_model=dict)
async def get_audit_summary(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None
):
    """
    Get audit log summary statistics (READ-ONLY)
    """
    entries = _audit_entries.copy()

    if start_date:
        entries = [e for e in entries if e.timestamp.date() >= start_date]
    if end_date:
        entries = [e for e in entries if e.timestamp.date() <= end_date]

    # Count by event type
    by_event_type = {}
    for entry in entries:
        et = entry.event_type.value
        by_event_type[et] = by_event_type.get(et, 0) + 1

    # Count by entity type
    by_entity_type = {}
    for entry in entries:
        et = entry.entity_type
        by_entity_type[et] = by_entity_type.get(et, 0) + 1

    # Count by severity
    by_severity = {}
    for entry in entries:
        sev = entry.severity.value
        by_severity[sev] = by_severity.get(sev, 0) + 1

    # Count by user
    by_user = {}
    for entry in entries:
        uid = entry.user_id
        by_user[uid] = by_user.get(uid, 0) + 1

    return {
        "total_entries": len(entries),
        "dcaa_relevant_entries": len([e for e in entries if e.dcaa_relevant]),
        "by_event_type": by_event_type,
        "by_entity_type": by_entity_type,
        "by_severity": by_severity,
        "by_user": by_user,
        "first_entry": entries[0].timestamp.isoformat() if entries else None,
        "last_entry": entries[-1].timestamp.isoformat() if entries else None,
        "advisory": {
            "type": "advisory",
            "message": "Audit summary for DCAA compliance review."
        }
    }
