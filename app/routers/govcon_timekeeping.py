# app/routers/govcon_timekeeping.py
"""
GovCon Timekeeping Router - DCAA Compliant Labor Tracking

Handles timekeeping with:
- Daily time entry and approval
- Labor category validation
- Contract/task charging
- Overtime tracking
- Audit trail for all changes

DCAA REQUIREMENTS:
- Employees must record time daily
- Supervisors must approve timesheets
- Changes require audit trail
- No post-facto corrections without documentation

CANONICAL LAWS ENFORCED:
- Advisory-only behavior
- Manual approval required
- Immutable audit trail
- Evidence required

ENTITLEMENT REQUIREMENT:
- Requires GovCon, Contractor, or Enterprise tier
- Server-side enforcement (not just UI gating)
"""

from fastapi import APIRouter, HTTPException, Depends, Request, status
from pydantic import BaseModel, Field, validator
from typing import Optional, List
from datetime import datetime, date, timedelta
from enum import Enum
from uuid import uuid4
from decimal import Decimal

from app.auth_context import get_current_context, AuthContext
from app.entitlements.tiers import require_govcon_entitlement
from app.govcon.contract import GOVCON_CONTRACT_VERSION


async def require_govcon_access(
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
):
    """Dependency that enforces GovCon entitlement."""
    require_govcon_entitlement(ctx["tier"], request=request)
    return ctx


router = APIRouter(
    prefix="/govcon/timekeeping",
    tags=["GovCon Timekeeping"],
    dependencies=[Depends(require_govcon_access)],
)


# =============================================================================
# ENUMS
# =============================================================================

class TimesheetStatus(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    CORRECTED = "corrected"


class ChargeType(str, Enum):
    DIRECT = "direct"
    INDIRECT = "indirect"
    OVERHEAD = "overhead"
    G_AND_A = "g_and_a"
    UNALLOWABLE = "unallowable"
    PTO = "pto"
    HOLIDAY = "holiday"


class LaborCategory(str, Enum):
    ENGINEER_I = "engineer_i"
    ENGINEER_II = "engineer_ii"
    ENGINEER_III = "engineer_iii"
    SENIOR_ENGINEER = "senior_engineer"
    PRINCIPAL_ENGINEER = "principal_engineer"
    ANALYST_I = "analyst_i"
    ANALYST_II = "analyst_ii"
    SENIOR_ANALYST = "senior_analyst"
    PROJECT_MANAGER = "project_manager"
    PROGRAM_MANAGER = "program_manager"
    ADMINISTRATIVE = "administrative"
    EXECUTIVE = "executive"


# =============================================================================
# MODELS
# =============================================================================

class TimeEntry(BaseModel):
    """Single time entry for a day"""
    id: str = Field(default_factory=lambda: str(uuid4()))
    date: date
    hours: float = Field(ge=0, le=24)
    charge_type: ChargeType
    contract_id: Optional[str] = None
    clin_number: Optional[str] = None
    task_order: Optional[str] = None
    work_description: str = Field(..., min_length=10, max_length=500)
    labor_category: LaborCategory

    # Rates (loaded from employee/contract)
    hourly_rate: Optional[float] = None
    loaded_rate: Optional[float] = None

    # Audit
    created_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: str
    modified_at: Optional[datetime] = None
    modified_by: Optional[str] = None
    modification_reason: Optional[str] = None

    @validator('hours')
    def validate_hours(cls, v):
        # Hours should be in 0.25 increments (15 min)
        if v % 0.25 != 0:
            raise ValueError("Hours must be in 15-minute increments (0.25)")
        return v


class Timesheet(BaseModel):
    """Weekly timesheet"""
    id: str = Field(default_factory=lambda: str(uuid4()))
    org_id: str = Field(..., description="Organization ID - REQUIRED for multi-tenant isolation")
    employee_id: str
    employee_name: str
    week_start: date = Field(..., description="Monday of the week")
    week_end: date = Field(..., description="Sunday of the week")

    # Entries
    entries: List[TimeEntry] = []

    # Totals (computed)
    total_hours: float = 0.0
    direct_hours: float = 0.0
    indirect_hours: float = 0.0
    overtime_hours: float = 0.0

    # Status
    status: TimesheetStatus = TimesheetStatus.DRAFT

    # Approval
    submitted_at: Optional[datetime] = None
    submitted_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    approved_by: Optional[str] = None
    rejection_reason: Optional[str] = None

    # Evidence
    evidence: Optional[dict] = None


class TimeEntryCreate(BaseModel):
    """Create time entry request"""
    date: date
    hours: float = Field(ge=0, le=24)
    charge_type: ChargeType
    contract_id: Optional[str] = None
    clin_number: Optional[str] = None
    task_order: Optional[str] = None
    work_description: str = Field(..., min_length=10)
    labor_category: LaborCategory


class TimesheetCorrection(BaseModel):
    """Timesheet correction request (requires evidence)"""
    entry_id: str
    original_hours: float
    corrected_hours: float
    correction_reason: str = Field(..., min_length=20)
    evidence: dict = Field(..., description="Evidence required for correction")
    confidence: float = Field(ge=0.85, le=1.0, description="Confidence must be >= 0.85")


# =============================================================================
# IN-MEMORY STORAGE
# =============================================================================

_timesheets: dict[str, Timesheet] = {}
_entries: dict[str, TimeEntry] = {}
_audit_log: List[dict] = []


def _log_audit(
    action: str,
    entity_type: str,
    entity_id: str,
    user_id: str,
    details: dict,
    org_id: Optional[str] = None,
    request_id: Optional[str] = None,
    before_state: Optional[dict] = None,
    after_state: Optional[dict] = None
):
    """
    Append to immutable audit log with full context.

    CANONICAL LAW: All mutations must be logged with:
    - request_id: Correlation ID for the request
    - org_id: Organization scope for multi-tenant filtering
    - before_state: State before mutation (for updates/deletes)
    - after_state: State after mutation (for creates/updates)
    """
    entry = {
        "id": str(uuid4()),
        "timestamp": datetime.utcnow().isoformat(),
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "user_id": user_id,
        "org_id": org_id,
        "request_id": request_id or str(uuid4()),  # Generate if not provided
        "details": details,
        "before_state": before_state,
        "after_state": after_state,
        "immutable": True,
        "dcaa_compliant": True
    }
    _audit_log.append(entry)
    return entry


def _require_timesheet_org_ownership(
    timesheet_id: str,
    ctx_org_id: str,
    user_id: str,
    request_id: str
) -> Timesheet:
    """
    P0 SECURITY: Verify org ownership before any access.

    CANONICAL LAW: Multi-tenant isolation
    - Resource MUST belong to caller's org
    - Logs unauthorized access attempts
    - Returns 403 on mismatch, 404 if not found
    """
    if timesheet_id not in _timesheets:
        raise HTTPException(status_code=404, detail="Timesheet not found")

    timesheet = _timesheets[timesheet_id]

    # P0 SECURITY: Verify org ownership
    if timesheet.org_id != ctx_org_id:
        # Log unauthorized access attempt
        _log_audit(
            action="unauthorized_access_blocked",
            entity_type="timesheet",
            entity_id=timesheet_id,
            user_id=user_id,
            details={
                "reason": "org_mismatch",
                "attempted_org": ctx_org_id,
                "resource_org": timesheet.org_id,
                "canonical_law": "multi_tenant_isolation"
            },
            org_id=ctx_org_id,
            request_id=request_id
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "ORG_ACCESS_DENIED",
                "message": "Resource does not belong to your organization",
                "canonical_law": "multi_tenant_isolation"
            }
        )

    return timesheet


def _compute_totals(timesheet: Timesheet) -> Timesheet:
    """Compute timesheet totals"""
    total = sum(e.hours for e in timesheet.entries)
    direct = sum(e.hours for e in timesheet.entries if e.charge_type == ChargeType.DIRECT)
    indirect = sum(e.hours for e in timesheet.entries if e.charge_type in [
        ChargeType.INDIRECT, ChargeType.OVERHEAD, ChargeType.G_AND_A
    ])

    # Overtime: hours over 40 per week
    overtime = max(0, total - 40)

    timesheet.total_hours = total
    timesheet.direct_hours = direct
    timesheet.indirect_hours = indirect
    timesheet.overtime_hours = overtime

    return timesheet


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/timesheets", response_model=List[dict])
async def list_timesheets(
    request: Request,
    employee_id: Optional[str] = None,
    status: Optional[TimesheetStatus] = None,
    week_start: Optional[date] = None,
    ctx: AuthContext = Depends(require_govcon_access)
):
    """
    List timesheets (READ-ONLY, advisory)

    P0 SECURITY: Only returns timesheets belonging to caller's org.
    """
    org_id = ctx["org_id"]

    # P0 SECURITY: Filter by org_id FIRST
    timesheets = [t for t in _timesheets.values() if t.org_id == org_id]

    if employee_id:
        timesheets = [t for t in timesheets if t.employee_id == employee_id]
    if status:
        timesheets = [t for t in timesheets if t.status == status]
    if week_start:
        timesheets = [t for t in timesheets if t.week_start == week_start]

    return [
        {
            "timesheet": t.dict(),
            "advisory": {
                "type": "advisory",
                "autonomous": False,
                "message": "Timesheet data for review. Approvals require manual action."
            }
        }
        for t in timesheets
    ]


@router.get("/timesheets/{timesheet_id}", response_model=dict)
async def get_timesheet(
    request: Request,
    timesheet_id: str,
    ctx: AuthContext = Depends(require_govcon_access)
):
    """
    Get timesheet by ID (READ-ONLY)

    P0 SECURITY: Requires org ownership verification.
    """
    request_id = getattr(request.state, "request_id", None) or str(uuid4())

    # P0 SECURITY: Verify org ownership
    timesheet = _require_timesheet_org_ownership(
        timesheet_id, ctx["org_id"], ctx["user_id"], request_id
    )
    timesheet = _compute_totals(timesheet)

    return {
        "timesheet": timesheet.dict(),
        "dcaa_compliance": {
            "daily_entries_complete": len(timesheet.entries) >= 5,  # Mon-Fri
            "descriptions_adequate": all(len(e.work_description) >= 10 for e in timesheet.entries),
            "direct_charges_have_contract": all(
                e.contract_id is not None
                for e in timesheet.entries
                if e.charge_type == ChargeType.DIRECT
            )
        },
        "advisory": {
            "type": "advisory",
            "autonomous": False,
            "message": "Review timesheet for DCAA compliance before approval."
        }
    }


@router.post("/timesheets", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_timesheet(
    request: Request,
    employee_id: str,
    employee_name: str,
    week_start: date,
    ctx: AuthContext = Depends(require_govcon_access)
):
    """
    Create a new timesheet for a week
    """
    # Week start must be Monday
    if week_start.weekday() != 0:
        raise HTTPException(
            status_code=400,
            detail="week_start must be a Monday"
        )

    week_end = week_start + timedelta(days=6)

    org_id = ctx["org_id"]

    # Check for duplicate (P0 SECURITY: org-scoped)
    existing = [
        t for t in _timesheets.values()
        if t.org_id == org_id and t.employee_id == employee_id and t.week_start == week_start
    ]
    if existing:
        raise HTTPException(
            status_code=400,
            detail="Timesheet already exists for this employee and week"
        )

    timesheet = Timesheet(
        org_id=org_id,  # P0 SECURITY: Store org ownership
        employee_id=employee_id,
        employee_name=employee_name,
        week_start=week_start,
        week_end=week_end
    )

    _timesheets[timesheet.id] = timesheet

    # Use auth context for proper audit logging
    request_id = getattr(request.state, "request_id", None) or str(uuid4())
    _log_audit(
        action="timesheet_created",
        entity_type="timesheet",
        entity_id=timesheet.id,
        user_id=ctx["user_id"],
        details={
            "employee_id": employee_id,
            "week_start": week_start.isoformat()
        },
        org_id=ctx["org_id"],
        request_id=request_id,
        after_state={"status": "draft", "employee_id": employee_id}
    )

    return {
        "timesheet_id": timesheet.id,
        "status": "draft",
        "message": "Timesheet created. Add daily entries and submit for approval."
    }


@router.post("/timesheets/{timesheet_id}/entries", response_model=dict)
async def add_time_entry(
    request: Request,
    timesheet_id: str,
    entry: TimeEntryCreate,
    ctx: AuthContext = Depends(require_govcon_access)
):
    """
    Add a time entry to a timesheet

    P0 SECURITY: Requires org ownership verification.
    """
    request_id = getattr(request.state, "request_id", None) or str(uuid4())

    # P0 SECURITY: Verify org ownership
    timesheet = _require_timesheet_org_ownership(
        timesheet_id, ctx["org_id"], ctx["user_id"], request_id
    )

    if timesheet.status not in [TimesheetStatus.DRAFT, TimesheetStatus.REJECTED]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot add entries to {timesheet.status} timesheet"
        )

    # Validate date is within week
    if not (timesheet.week_start <= entry.date <= timesheet.week_end):
        raise HTTPException(
            status_code=400,
            detail="Entry date must be within timesheet week"
        )

    # Validate direct charges have contract
    if entry.charge_type == ChargeType.DIRECT and not entry.contract_id:
        raise HTTPException(
            status_code=400,
            detail="Direct charges require contract_id"
        )

    time_entry = TimeEntry(
        date=entry.date,
        hours=entry.hours,
        charge_type=entry.charge_type,
        contract_id=entry.contract_id,
        clin_number=entry.clin_number,
        task_order=entry.task_order,
        work_description=entry.work_description,
        labor_category=entry.labor_category,
        created_by=ctx["user_id"]
    )

    timesheet.entries.append(time_entry)
    _entries[time_entry.id] = time_entry

    _log_audit(
        action="time_entry_added",
        entity_type="time_entry",
        entity_id=time_entry.id,
        user_id=ctx["user_id"],
        details={
            "timesheet_id": timesheet_id,
            "date": entry.date.isoformat(),
            "hours": entry.hours,
            "charge_type": entry.charge_type.value
        },
        org_id=ctx["org_id"],
        request_id=request_id,
        after_state={"hours": entry.hours, "charge_type": entry.charge_type.value}
    )

    timesheet = _compute_totals(timesheet)

    return {
        "entry_id": time_entry.id,
        "timesheet_totals": {
            "total_hours": timesheet.total_hours,
            "direct_hours": timesheet.direct_hours,
            "indirect_hours": timesheet.indirect_hours
        },
        "advisory": {
            "type": "advisory",
            "message": "Time entry added. Continue adding entries or submit for approval."
        }
    }


class TimesheetSubmitRequest(BaseModel):
    """Submit timesheet request - requires evidence per DCAA compliance"""
    evidence: dict = Field(..., description="Evidence of work performed (required for compliance)")
    attestation: bool = Field(..., description="Attestation that entries are accurate")


@router.post("/timesheets/{timesheet_id}/submit", response_model=dict)
async def submit_timesheet(
    request: Request,
    timesheet_id: str,
    submit_request: TimesheetSubmitRequest,
    ctx: AuthContext = Depends(require_govcon_access)
):
    """
    Submit timesheet for approval (MANUAL ACTION)

    P0 SECURITY: Requires org ownership verification.
    P1 COMPLIANCE: Requires evidence and attestation.
    """
    request_id = getattr(request.state, "request_id", None) or str(uuid4())

    # P0 SECURITY: Verify org ownership
    timesheet = _require_timesheet_org_ownership(
        timesheet_id, ctx["org_id"], ctx["user_id"], request_id
    )

    before_status = timesheet.status.value

    # P1 COMPLIANCE: Validate evidence is non-empty
    if not submit_request.evidence or len(submit_request.evidence) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "EVIDENCE_REQUIRED",
                "message": "Non-empty evidence is required for timesheet submission",
                "canonical_law": "evidence_required"
            }
        )

    # P1 COMPLIANCE: Require attestation
    if not submit_request.attestation:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "ATTESTATION_REQUIRED",
                "message": "Attestation that entries are accurate is required",
                "canonical_law": "evidence_required"
            }
        )

    if timesheet.status != TimesheetStatus.DRAFT:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot submit {timesheet.status} timesheet"
        )

    # Validate minimum entries (at least one per workday)
    workdays = [timesheet.week_start + timedelta(days=i) for i in range(5)]
    entry_dates = {e.date for e in timesheet.entries}
    missing_days = [d for d in workdays if d not in entry_dates]

    if missing_days:
        return {
            "submitted": False,
            "warning": "Missing time entries for some workdays",
            "missing_days": [d.isoformat() for d in missing_days],
            "advisory": {
                "type": "advisory",
                "message": "DCAA requires daily time recording. Please add entries for missing days."
            }
        }

    timesheet.status = TimesheetStatus.SUBMITTED
    timesheet.submitted_at = datetime.utcnow()
    timesheet.submitted_by = ctx["user_id"]
    timesheet.evidence = submit_request.evidence  # P1 COMPLIANCE: Store submission evidence

    _log_audit(
        action="timesheet_submitted",
        entity_type="timesheet",
        entity_id=timesheet_id,
        user_id=ctx["user_id"],
        details={
            "total_hours": timesheet.total_hours,
            "direct_hours": timesheet.direct_hours,
            "evidence": submit_request.evidence,  # P1 COMPLIANCE: Log evidence
            "attestation": submit_request.attestation
        },
        org_id=ctx["org_id"],
        request_id=request_id,
        before_state={"status": before_status},
        after_state={"status": "submitted", "submitted_at": timesheet.submitted_at.isoformat()}
    )

    return {
        "submitted": True,
        "timesheet_id": timesheet_id,
        "status": "submitted",
        "advisory": {
            "type": "advisory",
            "autonomous": False,
            "message": "Timesheet submitted. Awaiting supervisor approval."
        }
    }


class TimesheetApprovalRequest(BaseModel):
    """Approval request - requires non-empty evidence per DCAA compliance"""
    evidence: dict = Field(..., description="Approval evidence (required, must be non-empty)")
    review_notes: Optional[str] = Field(None, description="Optional reviewer notes")


@router.post("/timesheets/{timesheet_id}/approve", response_model=dict)
async def approve_timesheet(
    request: Request,
    timesheet_id: str,
    approval_request: TimesheetApprovalRequest,
    ctx: AuthContext = Depends(require_govcon_access)
):
    """
    Approve a timesheet (MANUAL SUPERVISOR ACTION)

    DCAA requires supervisor review and approval.

    P0 SECURITY: Requires org ownership verification.
    P1 COMPLIANCE: Requires non-empty evidence.
    """
    request_id = getattr(request.state, "request_id", None) or str(uuid4())
    approver_id = ctx["user_id"]

    # P1 COMPLIANCE: Validate evidence is non-empty
    if not approval_request.evidence or len(approval_request.evidence) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "EVIDENCE_REQUIRED",
                "message": "Non-empty approval evidence is required for timesheet approval",
                "canonical_law": "evidence_required"
            }
        )

    # P0 SECURITY: Verify org ownership
    timesheet = _require_timesheet_org_ownership(
        timesheet_id, ctx["org_id"], ctx["user_id"], request_id
    )

    before_status = timesheet.status.value

    if timesheet.status != TimesheetStatus.SUBMITTED:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot approve {timesheet.status} timesheet"
        )

    # Cannot approve own timesheet
    if approver_id == timesheet.employee_id:
        raise HTTPException(
            status_code=400,
            detail="Cannot approve own timesheet"
        )

    timesheet.status = TimesheetStatus.APPROVED
    timesheet.approved_at = datetime.utcnow()
    timesheet.approved_by = approver_id
    timesheet.evidence = approval_request.evidence  # P1 COMPLIANCE: Store approval evidence

    _log_audit(
        action="timesheet_approved",
        entity_type="timesheet",
        entity_id=timesheet_id,
        user_id=approver_id,
        details={
            "employee_id": timesheet.employee_id,
            "total_hours": timesheet.total_hours,
            "approval_evidence": approval_request.evidence,
            "review_notes": approval_request.review_notes
        },
        org_id=ctx["org_id"],
        request_id=request_id,
        before_state={"status": before_status},
        after_state={"status": "approved", "approved_by": approver_id}
    )

    return {
        "approved": True,
        "timesheet_id": timesheet_id,
        "approved_by": approver_id,
        "approved_at": timesheet.approved_at.isoformat(),
        "dcaa_compliant": True
    }


@router.post("/timesheets/{timesheet_id}/correct", response_model=dict)
async def correct_timesheet(
    request: Request,
    timesheet_id: str,
    correction: TimesheetCorrection,
    ctx: AuthContext = Depends(require_govcon_access)
):
    """
    Submit a timesheet correction (REQUIRES EVIDENCE AND APPROVAL)

    DCAA requires documentation for any post-approval corrections.

    CRITICAL: Lock-after-submit is ENFORCED.
    Submitted/Approved timesheets are IMMUTABLE.
    Admin unlock endpoint required for exceptional corrections.

    P0 SECURITY: Requires org ownership verification.
    """
    user_id = ctx["user_id"]
    org_id = ctx["org_id"]
    request_id = getattr(request.state, "request_id", None) or str(uuid4())

    # P0 SECURITY: Verify org ownership
    timesheet = _require_timesheet_org_ownership(
        timesheet_id, org_id, user_id, request_id
    )

    # CRITICAL: Lock-after-submit - FAIL CLOSED (Canonical Law)
    # Once submitted or approved, timesheets are IMMUTABLE
    # This is a hard enforcement - no bypass allowed without admin unlock
    if timesheet.status in [TimesheetStatus.SUBMITTED, TimesheetStatus.APPROVED]:
        _log_audit(
            action="correction_blocked_locked",
            entity_type="timesheet",
            entity_id=timesheet_id,
            user_id=user_id,
            details={
                "reason": "lock_after_submit",
                "timesheet_status": timesheet.status.value,
                "attempted_entry_id": correction.entry_id,
                "canonical_law": "immutable_after_submit"
            },
            org_id=org_id,
            request_id=request_id
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "TIMESHEET_LOCKED",
                "message": f"Cannot correct {timesheet.status.value} timesheet. Submitted/approved timesheets are immutable.",
                "status": timesheet.status.value,
                "immutable": True,
                "canonical_law": "lock_after_submit",
                "resolution": "Contact administrator to unlock timesheet for correction"
            }
        )

    # Find entry
    entry = next((e for e in timesheet.entries if e.id == correction.entry_id), None)
    if not entry:
        raise HTTPException(status_code=404, detail="Time entry not found")

    # Validate confidence (CANONICAL LAW: >= 0.85)
    if correction.confidence < 0.85:
        raise HTTPException(
            status_code=400,
            detail="Confidence must be >= 0.85 for corrections per canonical laws"
        )

    # DCAA COMPLIANCE: Preserve original entry, create correction entry
    # Original entries are NEVER modified - corrections are additive
    original_hours = entry.hours
    original_entry_id = entry.id

    # Capture before state for audit
    before_state = {
        "entry_id": original_entry_id,
        "hours": original_hours,
        "charge_type": entry.charge_type.value
    }

    # Mark original entry as superseded (but DO NOT delete or modify hours)
    entry.modified_at = datetime.utcnow()
    entry.modified_by = user_id
    entry.modification_reason = f"SUPERSEDED by correction: {correction.correction_reason}"

    # Create new correction entry that references original
    correction_entry = TimeEntry(
        date=entry.date,
        hours=correction.corrected_hours,
        charge_type=entry.charge_type,
        contract_id=entry.contract_id,
        clin_number=entry.clin_number,
        task_order=entry.task_order,
        work_description=f"[CORRECTION] {entry.work_description}",
        labor_category=entry.labor_category,
        created_by=user_id,
        modified_at=datetime.utcnow(),
        modified_by=user_id,
        modification_reason=correction.correction_reason
    )

    # Add correction entry to timesheet
    timesheet.entries.append(correction_entry)
    _entries[correction_entry.id] = correction_entry

    # Update timesheet status - requires re-approval
    timesheet.status = TimesheetStatus.CORRECTED

    # Capture after state
    after_state = {
        "correction_entry_id": correction_entry.id,
        "corrected_hours": correction.corrected_hours,
        "status": "corrected"
    }

    # Log BOTH the supersession and the correction with full context
    _log_audit(
        action="time_entry_superseded",
        entity_type="time_entry",
        entity_id=original_entry_id,
        user_id=user_id,
        details={
            "timesheet_id": timesheet_id,
            "original_hours": original_hours,
            "status": "superseded",
            "superseded_by": correction_entry.id
        },
        org_id=org_id,
        request_id=request_id,
        before_state=before_state
    )

    _log_audit(
        action="timesheet_corrected",
        entity_type="time_entry",
        entity_id=correction_entry.id,
        user_id=user_id,
        details={
            "timesheet_id": timesheet_id,
            "original_entry_id": original_entry_id,
            "original_hours": original_hours,
            "corrected_hours": correction.corrected_hours,
            "correction_reason": correction.correction_reason,
            "evidence": correction.evidence,
            "confidence": correction.confidence,
            "preserves_original": True
        },
        org_id=org_id,
        request_id=request_id,
        before_state=before_state,
        after_state=after_state
    )

    timesheet = _compute_totals(timesheet)

    return {
        "corrected": True,
        "original_entry_id": original_entry_id,
        "correction_entry_id": correction_entry.id,
        "original_hours": original_hours,
        "corrected_hours": correction.corrected_hours,
        "original_preserved": True,
        "new_totals": {
            "total_hours": timesheet.total_hours,
            "direct_hours": timesheet.direct_hours
        },
        "audit_logged": True,
        "requires_reapproval": True,
        "advisory": {
            "type": "advisory",
            "message": "Correction recorded. Original entry preserved. Re-approval REQUIRED per DCAA."
        }
    }


@router.get("/timesheets/{timesheet_id}/audit-trail", response_model=List[dict])
async def get_timesheet_audit_trail(
    request: Request,
    timesheet_id: str,
    ctx: AuthContext = Depends(require_govcon_access)
):
    """
    Get immutable audit trail for a timesheet (READ-ONLY)

    P0 SECURITY: Requires org ownership verification.
    """
    request_id = getattr(request.state, "request_id", None) or str(uuid4())
    org_id = ctx["org_id"]

    # P0 SECURITY: Verify org ownership before returning audit trail
    _require_timesheet_org_ownership(
        timesheet_id, org_id, ctx["user_id"], request_id
    )

    # P0 SECURITY: Filter by org_id FIRST, then by entity_id (defense in depth)
    trail = [
        entry for entry in _audit_log
        if entry.get("org_id") == org_id and (
            entry["entity_id"] == timesheet_id or
            entry.get("details", {}).get("timesheet_id") == timesheet_id
        )
    ]
    return trail


@router.get("/labor-distribution", response_model=dict)
async def get_labor_distribution(
    request: Request,
    start_date: date,
    end_date: date,
    contract_id: Optional[str] = None,
    ctx: AuthContext = Depends(require_govcon_access)
):
    """
    Get labor distribution report for DCAA compliance

    Shows labor hours by contract, category, and employee.

    P0 SECURITY: Only returns data for caller's organization.
    """
    org_id = ctx["org_id"]

    # P0 SECURITY: Filter by org_id FIRST, then by date range
    relevant_timesheets = [
        t for t in _timesheets.values()
        if t.org_id == org_id and  # P0 SECURITY: org isolation
           t.status == TimesheetStatus.APPROVED and
           t.week_start >= start_date and t.week_end <= end_date
    ]

    # Aggregate by contract
    by_contract: dict = {}
    by_employee: dict = {}
    by_category: dict = {}

    for ts in relevant_timesheets:
        for entry in ts.entries:
            if contract_id and entry.contract_id != contract_id:
                continue

            # By contract
            cid = entry.contract_id or "INDIRECT"
            if cid not in by_contract:
                by_contract[cid] = {"hours": 0, "entries": 0}
            by_contract[cid]["hours"] += entry.hours
            by_contract[cid]["entries"] += 1

            # By employee
            eid = ts.employee_id
            if eid not in by_employee:
                by_employee[eid] = {"name": ts.employee_name, "hours": 0}
            by_employee[eid]["hours"] += entry.hours

            # By category
            cat = entry.labor_category.value
            if cat not in by_category:
                by_category[cat] = {"hours": 0}
            by_category[cat]["hours"] += entry.hours

    return {
        "period": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat()
        },
        "by_contract": by_contract,
        "by_employee": by_employee,
        "by_category": by_category,
        "total_hours": sum(c["hours"] for c in by_contract.values()),
        "advisory": {
            "type": "advisory",
            "message": "Labor distribution data for DCAA compliance review."
        }
    }


# =============================================================================
# ADMIN UNLOCK ENDPOINT (Lock-After-Submit Exception Handler)
# =============================================================================

class AdminUnlockRequest(BaseModel):
    """Admin unlock request - requires strong evidence and justification"""
    justification: str = Field(..., min_length=50, description="Detailed justification for unlock (min 50 chars)")
    evidence: dict = Field(..., description="Evidence supporting the unlock request")
    supervisor_approval: str = Field(..., description="Supervisor who approved this unlock")
    dcaa_notification: bool = Field(default=False, description="Has DCAA been notified of this correction?")


@router.post("/timesheets/{timesheet_id}/admin-unlock", response_model=dict)
async def admin_unlock_timesheet(
    request: Request,
    timesheet_id: str,
    unlock_request: AdminUnlockRequest,
    ctx: AuthContext = Depends(require_govcon_access)
):
    """
    Admin unlock for submitted/approved timesheet (EXCEPTIONAL USE ONLY)

    DCAA CRITICAL: This endpoint allows unlocking a submitted/approved timesheet
    for correction. This action is:
    - Fully audited with before/after state
    - Requires detailed justification
    - Requires supervisor approval reference
    - Should be followed by re-approval after correction

    This is the ONLY way to correct a locked timesheet per canonical laws.

    P0 SECURITY: Requires org ownership verification.
    """
    admin_id = ctx["user_id"]
    org_id = ctx["org_id"]
    request_id = getattr(request.state, "request_id", None) or str(uuid4())

    # P0 SECURITY: Verify org ownership
    timesheet = _require_timesheet_org_ownership(
        timesheet_id, org_id, admin_id, request_id
    )
    previous_status = timesheet.status

    # Only unlock if actually locked
    if timesheet.status not in [TimesheetStatus.SUBMITTED, TimesheetStatus.APPROVED]:
        raise HTTPException(
            status_code=400,
            detail=f"Timesheet is {timesheet.status.value}, not locked. No unlock needed."
        )

    # Capture before state for audit
    before_state = {
        "status": timesheet.status.value,
        "submitted_at": timesheet.submitted_at.isoformat() if timesheet.submitted_at else None,
        "approved_at": timesheet.approved_at.isoformat() if timesheet.approved_at else None,
        "approved_by": timesheet.approved_by,
        "total_hours": timesheet.total_hours
    }

    # Set to CORRECTED status (allows corrections, requires re-approval)
    timesheet.status = TimesheetStatus.CORRECTED

    # Capture after state
    after_state = {
        "status": timesheet.status.value,
        "unlocked_at": datetime.utcnow().isoformat(),
        "unlocked_by": admin_id
    }

    # CRITICAL: Log admin unlock with full audit trail
    _log_audit(
        action="admin_unlock_timesheet",
        entity_type="timesheet",
        entity_id=timesheet_id,
        user_id=admin_id,
        details={
            "justification": unlock_request.justification,
            "supervisor_approval": unlock_request.supervisor_approval,
            "dcaa_notification": unlock_request.dcaa_notification,
            "evidence": unlock_request.evidence,
            "canonical_law": "admin_unlock_exception",
            "requires_reapproval": True
        },
        org_id=org_id,
        request_id=request_id,
        before_state=before_state,
        after_state=after_state
    )

    return {
        "unlocked": True,
        "timesheet_id": timesheet_id,
        "previous_status": previous_status.value,
        "new_status": timesheet.status.value,
        "audit_logged": True,
        "requires_reapproval": True,
        "advisory": {
            "type": "advisory",
            "autonomous": False,
            "message": "Timesheet unlocked for correction. MUST be re-approved after correction.",
            "dcaa_warning": "This action is fully audited. Ensure DCAA notification if required."
        }
    }
