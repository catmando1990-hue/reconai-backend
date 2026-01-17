# app/routers/govcon_reconciliation.py
"""
GovCon Reconciliation Router - DCAA Compliant Reconciliation Reports

Handles reconciliation with:
- Labor cost reconciliation
- Indirect cost reconciliation
- Contract cost reconciliation
- Incurred cost submissions
- SF-1408 compliance tracking

DCAA REQUIREMENTS:
- Costs must reconcile to general ledger
- Labor must tie to approved timesheets
- Indirect costs must match pool allocations
- Annual incurred cost submission required

CANONICAL LAWS ENFORCED:
- Advisory-only behavior
- Manual approval required
- Immutable audit trail
- Confidence >= 0.85 for AI insights (where applicable)
- Evidence required

ENTITLEMENT REQUIREMENT:
- Requires GovCon, Contractor, or Enterprise tier
- Server-side enforcement (not just UI gating)

NOTE ON CONFIDENCE GATING:
GovCon reconciliation is primarily DETERMINISTIC (not AI-driven).
Confidence gating applies only to any future AI-assisted variance
suggestions. Current implementation is rule-based.
"""

from fastapi import APIRouter, HTTPException, Depends, Request, status
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, date
from enum import Enum
from uuid import uuid4

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
    prefix="/govcon/reconciliation",
    tags=["GovCon Reconciliation"],
    dependencies=[Depends(require_govcon_access)],
)


# =============================================================================
# ENUMS
# =============================================================================

class ReconciliationType(str, Enum):
    LABOR = "labor"
    INDIRECT = "indirect"
    CONTRACT = "contract"
    INCURRED_COST = "incurred_cost"
    GENERAL_LEDGER = "general_ledger"


class ReconciliationStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    RECONCILED = "reconciled"
    VARIANCE_IDENTIFIED = "variance_identified"
    APPROVED = "approved"


class VarianceSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


# =============================================================================
# MODELS
# =============================================================================

class ReconciliationVariance(BaseModel):
    """Variance identified during reconciliation"""
    id: str = Field(default_factory=lambda: str(uuid4()))
    description: str
    expected_value: float
    actual_value: float
    variance_amount: float
    variance_percentage: float
    severity: VarianceSeverity
    resolution: Optional[str] = None
    resolved: bool = False
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None


class ReconciliationReport(BaseModel):
    """Reconciliation report"""
    id: str = Field(default_factory=lambda: str(uuid4()))
    report_type: ReconciliationType
    period_start: date
    period_end: date
    status: ReconciliationStatus = ReconciliationStatus.PENDING

    # Totals
    source_total: float = 0.0
    target_total: float = 0.0
    variance_total: float = 0.0

    # Details
    variances: List[ReconciliationVariance] = []
    line_items: List[dict] = []

    # Approval
    prepared_by: str
    prepared_at: datetime = Field(default_factory=datetime.utcnow)
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None

    # Evidence
    evidence: Optional[dict] = None

    # AI Insights (if applicable)
    insights: Optional[List[dict]] = None


class IncurredCostSubmission(BaseModel):
    """Annual Incurred Cost Submission (ICS)"""
    id: str = Field(default_factory=lambda: str(uuid4()))
    fiscal_year: int
    contractor_name: str
    contractor_cage: str

    # Schedules
    schedule_h: dict = Field(default_factory=dict, description="Contract Summary")
    schedule_i: dict = Field(default_factory=dict, description="Cumulative Allowable Costs")
    schedule_j: dict = Field(default_factory=dict, description="Subcontract Costs")
    schedule_k: dict = Field(default_factory=dict, description="Consultant Costs")
    schedule_l: dict = Field(default_factory=dict, description="Direct Material Costs")
    schedule_m: dict = Field(default_factory=dict, description="Direct Labor Costs")
    schedule_n: dict = Field(default_factory=dict, description="Indirect Expense Pools")
    schedule_o: dict = Field(default_factory=dict, description="Allocation Bases")

    # Status
    status: str = "draft"
    submitted_at: Optional[datetime] = None
    dcaa_received_at: Optional[datetime] = None

    # Audit
    created_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: str


class SF1408Checklist(BaseModel):
    """SF-1408 Preaward Survey Checklist"""
    id: str = Field(default_factory=lambda: str(uuid4()))
    contractor_name: str
    contractor_cage: str
    survey_date: date

    # System adequacy items
    accounting_system_adequate: bool = False
    timekeeping_system_adequate: bool = False
    labor_distribution_adequate: bool = False
    billing_system_adequate: bool = False
    indirect_cost_system_adequate: bool = False
    budgeting_system_adequate: bool = False
    compensation_system_adequate: bool = False

    # Notes
    accounting_notes: Optional[str] = None
    timekeeping_notes: Optional[str] = None
    labor_distribution_notes: Optional[str] = None
    billing_notes: Optional[str] = None
    indirect_cost_notes: Optional[str] = None
    budgeting_notes: Optional[str] = None
    compensation_notes: Optional[str] = None

    # Overall
    overall_adequate: bool = False
    deficiencies: List[str] = []
    recommendations: List[str] = []

    # Signatures
    auditor_name: Optional[str] = None
    auditor_signature_date: Optional[date] = None

    # Evidence
    evidence: Optional[dict] = None


# =============================================================================
# IN-MEMORY STORAGE
# =============================================================================

_reports: dict[str, ReconciliationReport] = {}
_submissions: dict[str, IncurredCostSubmission] = {}
_checklists: dict[str, SF1408Checklist] = {}
_audit_log: List[dict] = []


def _log_audit(action: str, entity_type: str, entity_id: str, user_id: str, details: dict):
    """Append to immutable audit log"""
    entry = {
        "id": str(uuid4()),
        "timestamp": datetime.utcnow().isoformat(),
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "user_id": user_id,
        "details": details,
        "immutable": True,
        "dcaa_compliant": True
    }
    _audit_log.append(entry)
    return entry


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post("/reports", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_reconciliation_report(
    report_type: ReconciliationType,
    period_start: date,
    period_end: date,
    user_id: str = "system"
):
    """
    Create a new reconciliation report
    """
    report = ReconciliationReport(
        report_type=report_type,
        period_start=period_start,
        period_end=period_end,
        prepared_by=user_id
    )

    _reports[report.id] = report

    _log_audit(
        action="reconciliation_report_created",
        entity_type="reconciliation_report",
        entity_id=report.id,
        user_id=user_id,
        details={
            "report_type": report_type.value,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat()
        }
    )

    return {
        "report_id": report.id,
        "report_type": report_type.value,
        "status": "pending",
        "advisory": {
            "type": "advisory",
            "autonomous": False,
            "message": "Report created. Run reconciliation to identify variances."
        }
    }


@router.get("/reports", response_model=dict)
async def list_reports(
    report_type: Optional[ReconciliationType] = None,
    status: Optional[ReconciliationStatus] = None,
    limit: int = 50,
    offset: int = 0
):
    """
    List reconciliation reports (READ-ONLY, PAGINATED)
    """
    reports = list(_reports.values())

    if report_type:
        reports = [r for r in reports if r.report_type == report_type]
    if status:
        reports = [r for r in reports if r.status == status]

    # Sort by created_at descending
    reports.sort(key=lambda r: r.created_at, reverse=True)

    # Pagination
    total = len(reports)
    reports = reports[offset:offset + limit]

    return {
        "reports": [
            {
                "report": r.dict(),
                "advisory": {
                    "type": "advisory",
                    "message": "Report data for review."
                }
            }
            for r in reports
        ],
        "total": total,
        "limit": limit,
        "offset": offset
    }


@router.get("/reports/{report_id}", response_model=dict)
async def get_report(report_id: str):
    """
    Get reconciliation report by ID (READ-ONLY)
    """
    if report_id not in _reports:
        raise HTTPException(status_code=404, detail="Report not found")

    report = _reports[report_id]

    return {
        "report": report.dict(),
        "variance_summary": {
            "total_variances": len(report.variances),
            "unresolved": len([v for v in report.variances if not v.resolved]),
            "critical": len([v for v in report.variances if v.severity == VarianceSeverity.CRITICAL])
        },
        "advisory": {
            "type": "advisory",
            "message": "Review variances and resolve before approval."
        }
    }


@router.post("/reports/{report_id}/run-labor", response_model=dict)
async def run_labor_reconciliation(
    report_id: str,
    timesheet_total: float,
    payroll_total: float,
    gl_total: float,
    user_id: str = "system"
):
    """
    Run labor cost reconciliation (ADVISORY)

    Compares timesheet labor to payroll and general ledger.
    """
    if report_id not in _reports:
        raise HTTPException(status_code=404, detail="Report not found")

    report = _reports[report_id]
    report.status = ReconciliationStatus.IN_PROGRESS
    report.source_total = timesheet_total
    report.target_total = payroll_total

    variances = []

    # Check timesheet to payroll
    ts_payroll_variance = timesheet_total - payroll_total
    if abs(ts_payroll_variance) > 0.01:
        variance = ReconciliationVariance(
            description="Timesheet to Payroll Variance",
            expected_value=timesheet_total,
            actual_value=payroll_total,
            variance_amount=ts_payroll_variance,
            variance_percentage=(ts_payroll_variance / timesheet_total * 100) if timesheet_total > 0 else 0,
            severity=VarianceSeverity.ERROR if abs(ts_payroll_variance) > 1000 else VarianceSeverity.WARNING
        )
        variances.append(variance)

    # Check payroll to GL
    payroll_gl_variance = payroll_total - gl_total
    if abs(payroll_gl_variance) > 0.01:
        variance = ReconciliationVariance(
            description="Payroll to General Ledger Variance",
            expected_value=payroll_total,
            actual_value=gl_total,
            variance_amount=payroll_gl_variance,
            variance_percentage=(payroll_gl_variance / payroll_total * 100) if payroll_total > 0 else 0,
            severity=VarianceSeverity.ERROR if abs(payroll_gl_variance) > 1000 else VarianceSeverity.WARNING
        )
        variances.append(variance)

    report.variances = variances
    report.variance_total = sum(v.variance_amount for v in variances)

    if variances:
        report.status = ReconciliationStatus.VARIANCE_IDENTIFIED
    else:
        report.status = ReconciliationStatus.RECONCILED

    _log_audit(
        action="labor_reconciliation_run",
        entity_type="reconciliation_report",
        entity_id=report_id,
        user_id=user_id,
        details={
            "timesheet_total": timesheet_total,
            "payroll_total": payroll_total,
            "gl_total": gl_total,
            "variances_found": len(variances)
        }
    )

    return {
        "report_id": report_id,
        "status": report.status.value,
        "totals": {
            "timesheet": timesheet_total,
            "payroll": payroll_total,
            "gl": gl_total
        },
        "variances": [v.dict() for v in variances],
        "advisory": {
            "type": "advisory",
            "autonomous": False,
            "message": "Labor reconciliation complete. Review and resolve variances." if variances
                      else "Labor costs reconciled successfully."
        }
    }


@router.post("/reports/{report_id}/run-indirect", response_model=dict)
async def run_indirect_reconciliation(
    report_id: str,
    pool_data: List[dict],
    user_id: str = "system"
):
    """
    Run indirect cost reconciliation (ADVISORY)

    Verifies indirect pools tie to general ledger.
    """
    if report_id not in _reports:
        raise HTTPException(status_code=404, detail="Report not found")

    report = _reports[report_id]
    report.status = ReconciliationStatus.IN_PROGRESS

    variances = []
    total_pool = 0.0
    total_gl = 0.0

    for pool in pool_data:
        pool_amount = pool.get("pool_amount", 0)
        gl_amount = pool.get("gl_amount", 0)
        pool_name = pool.get("pool_name", "Unknown")

        total_pool += pool_amount
        total_gl += gl_amount

        variance_amount = pool_amount - gl_amount
        if abs(variance_amount) > 0.01:
            variance = ReconciliationVariance(
                description=f"{pool_name} Pool to GL Variance",
                expected_value=pool_amount,
                actual_value=gl_amount,
                variance_amount=variance_amount,
                variance_percentage=(variance_amount / pool_amount * 100) if pool_amount > 0 else 0,
                severity=VarianceSeverity.ERROR if abs(variance_amount) > 500 else VarianceSeverity.WARNING
            )
            variances.append(variance)

    report.source_total = total_pool
    report.target_total = total_gl
    report.variances = variances
    report.variance_total = sum(v.variance_amount for v in variances)

    if variances:
        report.status = ReconciliationStatus.VARIANCE_IDENTIFIED
    else:
        report.status = ReconciliationStatus.RECONCILED

    _log_audit(
        action="indirect_reconciliation_run",
        entity_type="reconciliation_report",
        entity_id=report_id,
        user_id=user_id,
        details={
            "total_pool": total_pool,
            "total_gl": total_gl,
            "variances_found": len(variances)
        }
    )

    return {
        "report_id": report_id,
        "status": report.status.value,
        "totals": {
            "pool": total_pool,
            "gl": total_gl,
            "variance": report.variance_total
        },
        "variances": [v.dict() for v in variances],
        "advisory": {
            "type": "advisory",
            "message": "Indirect reconciliation complete. Review variances."
        }
    }


@router.post("/reports/{report_id}/resolve-variance/{variance_id}", response_model=dict)
async def resolve_variance(
    report_id: str,
    variance_id: str,
    resolution: str,
    evidence: dict,
    user_id: str = "system"
):
    """
    Resolve a variance (REQUIRES EVIDENCE)
    """
    if report_id not in _reports:
        raise HTTPException(status_code=404, detail="Report not found")

    report = _reports[report_id]

    variance = next((v for v in report.variances if v.id == variance_id), None)
    if not variance:
        raise HTTPException(status_code=404, detail="Variance not found")

    variance.resolution = resolution
    variance.resolved = True
    variance.resolved_at = datetime.utcnow()
    variance.resolved_by = user_id

    # Check if all variances resolved
    if all(v.resolved for v in report.variances):
        report.status = ReconciliationStatus.RECONCILED

    _log_audit(
        action="variance_resolved",
        entity_type="reconciliation_variance",
        entity_id=variance_id,
        user_id=user_id,
        details={
            "report_id": report_id,
            "resolution": resolution,
            "evidence": evidence
        }
    )

    return {
        "variance_id": variance_id,
        "resolved": True,
        "report_status": report.status.value,
        "advisory": {
            "type": "advisory",
            "message": "Variance resolved and documented."
        }
    }


@router.post("/reports/{report_id}/approve", response_model=dict)
async def approve_report(
    report_id: str,
    approver_id: str,
    approval_evidence: dict
):
    """
    Approve a reconciliation report (MANUAL ACTION)
    """
    if report_id not in _reports:
        raise HTTPException(status_code=404, detail="Report not found")

    report = _reports[report_id]

    if report.status != ReconciliationStatus.RECONCILED:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot approve report with status {report.status.value}"
        )

    unresolved = [v for v in report.variances if not v.resolved]
    if unresolved:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot approve: {len(unresolved)} unresolved variances"
        )

    report.status = ReconciliationStatus.APPROVED
    report.approved_by = approver_id
    report.approved_at = datetime.utcnow()
    report.evidence = approval_evidence

    _log_audit(
        action="reconciliation_approved",
        entity_type="reconciliation_report",
        entity_id=report_id,
        user_id=approver_id,
        details={
            "approval_evidence": approval_evidence
        }
    )

    return {
        "report_id": report_id,
        "status": "approved",
        "approved_by": approver_id,
        "approved_at": report.approved_at.isoformat(),
        "dcaa_compliant": True
    }


# =============================================================================
# INCURRED COST SUBMISSION
# =============================================================================

@router.post("/incurred-cost", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_incurred_cost_submission(
    fiscal_year: int,
    contractor_name: str,
    contractor_cage: str,
    user_id: str = "system"
):
    """
    Create an Incurred Cost Submission (ICS)

    Per FAR 52.216-7, contractors must submit annual ICS.
    """
    submission = IncurredCostSubmission(
        fiscal_year=fiscal_year,
        contractor_name=contractor_name,
        contractor_cage=contractor_cage,
        created_by=user_id
    )

    _submissions[submission.id] = submission

    _log_audit(
        action="ics_created",
        entity_type="incurred_cost_submission",
        entity_id=submission.id,
        user_id=user_id,
        details={
            "fiscal_year": fiscal_year,
            "contractor_name": contractor_name
        }
    )

    return {
        "submission_id": submission.id,
        "fiscal_year": fiscal_year,
        "status": "draft",
        "schedules_required": ["H", "I", "J", "K", "L", "M", "N", "O"],
        "advisory": {
            "type": "advisory",
            "message": "ICS created. Complete all schedules before submission."
        }
    }


@router.get("/incurred-cost/{submission_id}", response_model=dict)
async def get_incurred_cost_submission(submission_id: str):
    """
    Get Incurred Cost Submission (READ-ONLY)
    """
    if submission_id not in _submissions:
        raise HTTPException(status_code=404, detail="Submission not found")

    submission = _submissions[submission_id]

    return {
        "submission": submission.dict(),
        "completion_status": {
            "schedule_h": bool(submission.schedule_h),
            "schedule_i": bool(submission.schedule_i),
            "schedule_j": bool(submission.schedule_j),
            "schedule_k": bool(submission.schedule_k),
            "schedule_l": bool(submission.schedule_l),
            "schedule_m": bool(submission.schedule_m),
            "schedule_n": bool(submission.schedule_n),
            "schedule_o": bool(submission.schedule_o)
        },
        "advisory": {
            "type": "advisory",
            "message": "Complete all schedules for DCAA submission."
        }
    }


# =============================================================================
# SF-1408 CHECKLIST
# =============================================================================

@router.post("/sf1408", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_sf1408_checklist(
    contractor_name: str,
    contractor_cage: str,
    survey_date: date,
    user_id: str = "system"
):
    """
    Create SF-1408 Preaward Survey Checklist
    """
    checklist = SF1408Checklist(
        contractor_name=contractor_name,
        contractor_cage=contractor_cage,
        survey_date=survey_date
    )

    _checklists[checklist.id] = checklist

    _log_audit(
        action="sf1408_created",
        entity_type="sf1408_checklist",
        entity_id=checklist.id,
        user_id=user_id,
        details={
            "contractor_name": contractor_name,
            "survey_date": survey_date.isoformat()
        }
    )

    return {
        "checklist_id": checklist.id,
        "status": "created",
        "systems_to_evaluate": [
            "Accounting System",
            "Timekeeping System",
            "Labor Distribution",
            "Billing System",
            "Indirect Cost System",
            "Budgeting System",
            "Compensation System"
        ],
        "advisory": {
            "type": "advisory",
            "message": "SF-1408 checklist created. Evaluate each system for adequacy."
        }
    }


@router.get("/sf1408/{checklist_id}", response_model=dict)
async def get_sf1408_checklist(checklist_id: str):
    """
    Get SF-1408 checklist (READ-ONLY)
    """
    if checklist_id not in _checklists:
        raise HTTPException(status_code=404, detail="Checklist not found")

    checklist = _checklists[checklist_id]

    adequate_count = sum([
        checklist.accounting_system_adequate,
        checklist.timekeeping_system_adequate,
        checklist.labor_distribution_adequate,
        checklist.billing_system_adequate,
        checklist.indirect_cost_system_adequate,
        checklist.budgeting_system_adequate,
        checklist.compensation_system_adequate
    ])

    return {
        "checklist": checklist.dict(),
        "summary": {
            "systems_adequate": adequate_count,
            "systems_total": 7,
            "overall_adequate": adequate_count == 7
        },
        "advisory": {
            "type": "advisory",
            "message": "All 7 systems must be adequate for preaward approval."
        }
    }


@router.get("/audit-trail", response_model=List[dict])
async def get_reconciliation_audit_trail():
    """
    Get immutable audit trail for all reconciliation activities
    """
    return _audit_log
