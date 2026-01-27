# app/routers/payroll.py
"""
Payroll Router — All 10 Sub-Domains

DOMAIN RULES:
- Payroll is WRITE-ENABLED (draft → approved → locked)
- Every mutation is audit-logged with before/after values
- All queries are org-isolated via AuthContext
- Locked pay runs are immutable
- Snapshots generated on lock (irreversible)
- Payroll NEVER calls DCAA or CFO directly
- Fail-closed on audit failures

Sub-domains:
  1. People           6. Benefits
  2. Compensation     7. Accounting
  3. Time & Labor     8. Compliance
  4. Pay Runs         9. Audit (read-only log)
  5. Taxes           10. Snapshots (read-only)
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.auth_context import AuthContext, get_current_context
from app.payroll import db as payroll_db
from app.payroll.models import (
    BenefitEnrollmentCreateRequest,
    CompensationCreateRequest,
    CompensationUpdateRequest,
    PayRunAddLineRequest,
    PayRunApproveRequest,
    PayRunCreateRequest,
    PayRunLockRequest,
    PersonCreateRequest,
    PersonUpdateRequest,
    TaxWithholdingCreateRequest,
    TimeEntryCreateRequest,
    TimeEntryUpdateRequest,
)
from app.payroll.snapshots import generate_all_snapshots
from app.services.audit_service import AuditServiceError, record_audit

router = APIRouter(prefix="/api/payroll", tags=["payroll"])


# =============================================================================
# HELPERS
# =============================================================================

def _new_id() -> str:
    return str(uuid.uuid4())


def _get_request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or str(uuid.uuid4())


def _not_found(entity: str, entity_id: str, request_id: str):
    raise HTTPException(
        status_code=404,
        detail={
            "error": f"{entity} not found",
            "entity_id": entity_id,
            "request_id": request_id,
        },
    )


def _locked_error(request_id: str):
    raise HTTPException(
        status_code=409,
        detail={
            "error": "Pay run is locked and cannot be modified",
            "request_id": request_id,
        },
    )


def _audit_or_abort(
    actor: str, action: str, entity: str, entity_id: str,
    payload: Dict[str, Any], request_id: str,
) -> None:
    """Record audit event. Fail-closed: raises HTTPException on failure."""
    try:
        record_audit(
            actor=actor,
            action=action,
            entity=entity,
            entity_id=entity_id,
            payload=payload,
            request_id=request_id,
        )
    except AuditServiceError:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Audit logging failed — operation aborted (fail-closed)",
                "request_id": request_id,
            },
        )


# =============================================================================
# 1. PEOPLE
# =============================================================================

@router.post("/people")
async def create_person(
    body: PersonCreateRequest,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
) -> Dict[str, Any]:
    request_id = _get_request_id(request)
    org_id = ctx["org_id"]
    person_id = _new_id()

    payroll_db.create_person(
        id=person_id, org_id=org_id, employee_id=body.employee_id,
        first_name=body.first_name, last_name=body.last_name,
        email=body.email, department=body.department,
        job_title=body.job_title, hire_date=body.hire_date,
        status=body.status.value,
    )

    _audit_or_abort(
        actor=ctx["user_id"], action="payroll_person_created",
        entity="payroll_people", entity_id=person_id,
        payload={"employee_id": body.employee_id, "name": f"{body.first_name} {body.last_name}"},
        request_id=request_id,
    )

    record = payroll_db.get_person(org_id, person_id)
    return {"status": "ok", "data": record, "request_id": request_id}


@router.get("/people")
async def list_people(
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    limit: int = Query(default=100, le=500),
) -> Dict[str, Any]:
    request_id = _get_request_id(request)
    items = payroll_db.list_people(ctx["org_id"], limit=limit)
    return {"status": "ok", "items": items, "total": len(items), "request_id": request_id}


@router.get("/people/{person_id}")
async def get_person(
    person_id: str,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
) -> Dict[str, Any]:
    request_id = _get_request_id(request)
    record = payroll_db.get_person(ctx["org_id"], person_id)
    if not record:
        _not_found("Person", person_id, request_id)
    return {"status": "ok", "data": record, "request_id": request_id}


@router.patch("/people/{person_id}")
async def update_person(
    person_id: str,
    body: PersonUpdateRequest,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
) -> Dict[str, Any]:
    request_id = _get_request_id(request)
    org_id = ctx["org_id"]

    before = payroll_db.get_person(org_id, person_id)
    if not before:
        _not_found("Person", person_id, request_id)

    updates = body.model_dump(exclude_none=True, exclude={"reason_code"})
    # Convert enum to value if present
    if "status" in updates and hasattr(updates["status"], "value"):
        updates["status"] = updates["status"].value

    after = payroll_db.update_person(org_id, person_id, updates)

    _audit_or_abort(
        actor=ctx["user_id"], action="payroll_person_updated",
        entity="payroll_people", entity_id=person_id,
        payload={"before": before, "after": after, "reason_code": body.reason_code},
        request_id=request_id,
    )

    return {"status": "ok", "data": after, "request_id": request_id}


# =============================================================================
# 2. COMPENSATION
# =============================================================================

@router.post("/compensation")
async def create_compensation(
    body: CompensationCreateRequest,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
) -> Dict[str, Any]:
    request_id = _get_request_id(request)
    org_id = ctx["org_id"]
    comp_id = _new_id()

    payroll_db.create_compensation(
        id=comp_id, org_id=org_id, person_id=body.person_id,
        comp_type=body.comp_type.value, rate=body.rate,
        currency=body.currency, effective_date=body.effective_date,
        end_date=body.end_date,
    )

    _audit_or_abort(
        actor=ctx["user_id"], action="payroll_compensation_created",
        entity="payroll_compensation", entity_id=comp_id,
        payload={"person_id": body.person_id, "comp_type": body.comp_type.value, "rate": body.rate},
        request_id=request_id,
    )

    return {"status": "ok", "data": {"id": comp_id}, "request_id": request_id}


@router.get("/compensation")
async def list_compensation(
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    person_id: Optional[str] = Query(default=None),
    limit: int = Query(default=100, le=500),
) -> Dict[str, Any]:
    request_id = _get_request_id(request)
    items = payroll_db.list_compensation(ctx["org_id"], person_id=person_id, limit=limit)
    return {"status": "ok", "items": items, "total": len(items), "request_id": request_id}


# =============================================================================
# 3. TIME & LABOR
# =============================================================================

@router.post("/time-entries")
async def create_time_entry(
    body: TimeEntryCreateRequest,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
) -> Dict[str, Any]:
    request_id = _get_request_id(request)
    org_id = ctx["org_id"]
    entry_id = _new_id()

    payroll_db.create_time_entry(
        id=entry_id, org_id=org_id, person_id=body.person_id,
        work_date=body.work_date, hours=body.hours,
        cost_code=body.cost_code, description=body.description,
    )

    _audit_or_abort(
        actor=ctx["user_id"], action="payroll_time_entry_created",
        entity="payroll_time_entries", entity_id=entry_id,
        payload={"person_id": body.person_id, "work_date": body.work_date, "hours": body.hours},
        request_id=request_id,
    )

    record = payroll_db.get_time_entry(org_id, entry_id)
    return {"status": "ok", "data": record, "request_id": request_id}


@router.get("/time-entries")
async def list_time_entries(
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    person_id: Optional[str] = Query(default=None),
    limit: int = Query(default=100, le=500),
) -> Dict[str, Any]:
    request_id = _get_request_id(request)
    items = payroll_db.list_time_entries(ctx["org_id"], person_id=person_id, limit=limit)
    return {"status": "ok", "items": items, "total": len(items), "request_id": request_id}


@router.patch("/time-entries/{entry_id}")
async def update_time_entry(
    entry_id: str,
    body: TimeEntryUpdateRequest,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
) -> Dict[str, Any]:
    request_id = _get_request_id(request)
    org_id = ctx["org_id"]

    before = payroll_db.get_time_entry(org_id, entry_id)
    if not before:
        _not_found("Time entry", entry_id, request_id)

    updates = body.model_dump(exclude_none=True, exclude={"reason_code"})
    if "status" in updates and hasattr(updates["status"], "value"):
        updates["status"] = updates["status"].value

    after = payroll_db.update_time_entry(org_id, entry_id, updates)

    _audit_or_abort(
        actor=ctx["user_id"], action="payroll_time_entry_updated",
        entity="payroll_time_entries", entity_id=entry_id,
        payload={"before": before, "after": after, "reason_code": body.reason_code},
        request_id=request_id,
    )

    return {"status": "ok", "data": after, "request_id": request_id}


# =============================================================================
# 4. PAY RUNS
# =============================================================================

@router.post("/pay-runs")
async def create_pay_run(
    body: PayRunCreateRequest,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
) -> Dict[str, Any]:
    request_id = _get_request_id(request)
    org_id = ctx["org_id"]
    run_id = _new_id()

    payroll_db.create_pay_run(
        id=run_id, org_id=org_id,
        pay_period_start=body.pay_period_start,
        pay_period_end=body.pay_period_end,
        description=body.description,
    )

    _audit_or_abort(
        actor=ctx["user_id"], action="payroll_pay_run_created",
        entity="payroll_pay_runs", entity_id=run_id,
        payload={"pay_period_start": body.pay_period_start, "pay_period_end": body.pay_period_end},
        request_id=request_id,
    )

    record = payroll_db.get_pay_run(org_id, run_id)
    return {"status": "ok", "data": record, "request_id": request_id}


@router.get("/pay-runs")
async def list_pay_runs(
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    limit: int = Query(default=50, le=200),
) -> Dict[str, Any]:
    request_id = _get_request_id(request)
    items = payroll_db.list_pay_runs(ctx["org_id"], limit=limit)
    return {"status": "ok", "items": items, "total": len(items), "request_id": request_id}


@router.get("/pay-runs/{run_id}")
async def get_pay_run(
    run_id: str,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
) -> Dict[str, Any]:
    request_id = _get_request_id(request)
    record = payroll_db.get_pay_run(ctx["org_id"], run_id)
    if not record:
        _not_found("Pay run", run_id, request_id)
    return {"status": "ok", "data": record, "request_id": request_id}


@router.post("/pay-runs/{run_id}/lines")
async def add_pay_run_line(
    run_id: str,
    body: PayRunAddLineRequest,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
) -> Dict[str, Any]:
    request_id = _get_request_id(request)
    org_id = ctx["org_id"]

    run = payroll_db.get_pay_run(org_id, run_id)
    if not run:
        _not_found("Pay run", run_id, request_id)
    if run["status"] != "draft":
        _locked_error(request_id)

    line_id = _new_id()
    payroll_db.add_pay_run_line(
        id=line_id, org_id=org_id, pay_run_id=run_id,
        person_id=body.person_id, gross_amount=body.gross_amount,
        tax_amount=body.tax_amount, benefits_amount=body.benefits_amount,
        deductions_amount=body.deductions_amount, net_amount=body.net_amount,
        hours_worked=body.hours_worked, cost_code=body.cost_code,
    )

    _audit_or_abort(
        actor=ctx["user_id"], action="payroll_line_added",
        entity="payroll_pay_run_lines", entity_id=line_id,
        payload={"pay_run_id": run_id, "person_id": body.person_id, "gross_amount": body.gross_amount},
        request_id=request_id,
    )

    return {"status": "ok", "data": {"id": line_id, "pay_run_id": run_id}, "request_id": request_id}


@router.get("/pay-runs/{run_id}/lines")
async def get_pay_run_lines(
    run_id: str,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
) -> Dict[str, Any]:
    request_id = _get_request_id(request)
    items = payroll_db.get_pay_run_lines(ctx["org_id"], run_id)
    return {"status": "ok", "items": items, "total": len(items), "request_id": request_id}


@router.post("/pay-runs/{run_id}/approve")
async def approve_pay_run(
    run_id: str,
    body: PayRunApproveRequest,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
) -> Dict[str, Any]:
    """Transition pay run: draft → approved."""
    request_id = _get_request_id(request)
    org_id = ctx["org_id"]

    run = payroll_db.get_pay_run(org_id, run_id)
    if not run:
        _not_found("Pay run", run_id, request_id)
    if run["status"] != "draft":
        raise HTTPException(
            status_code=409,
            detail={
                "error": f"Pay run is '{run['status']}', must be 'draft' to approve",
                "request_id": request_id,
            },
        )

    payroll_db.update_pay_run_status(org_id, run_id, "approved")

    _audit_or_abort(
        actor=ctx["user_id"], action="payroll_pay_run_approved",
        entity="payroll_pay_runs", entity_id=run_id,
        payload={"before_status": "draft", "after_status": "approved", "reason_code": body.reason_code},
        request_id=request_id,
    )

    record = payroll_db.get_pay_run(org_id, run_id)
    return {"status": "ok", "data": record, "request_id": request_id}


@router.post("/pay-runs/{run_id}/lock")
async def lock_pay_run(
    run_id: str,
    body: PayRunLockRequest,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
) -> Dict[str, Any]:
    """
    Transition pay run: approved → locked (IRREVERSIBLE).

    Generates immutable, hash-sealed snapshots if generate_snapshots=True.
    """
    request_id = _get_request_id(request)
    org_id = ctx["org_id"]

    run = payroll_db.get_pay_run(org_id, run_id)
    if not run:
        _not_found("Pay run", run_id, request_id)
    if run["status"] != "approved":
        raise HTTPException(
            status_code=409,
            detail={
                "error": f"Pay run is '{run['status']}', must be 'approved' to lock",
                "request_id": request_id,
            },
        )

    locked_at = datetime.utcnow().isoformat()
    snapshot_id = None
    snapshot_ids = {}

    if body.generate_snapshots:
        line_items = payroll_db.get_pay_run_lines(org_id, run_id)
        snapshot_ids = generate_all_snapshots(org_id, run_id, run, line_items)
        snapshot_id = snapshot_ids.get("payroll")

    payroll_db.update_pay_run_status(
        org_id, run_id, "locked",
        locked_at=locked_at, snapshot_id=snapshot_id,
    )

    _audit_or_abort(
        actor=ctx["user_id"], action="payroll_pay_run_locked",
        entity="payroll_pay_runs", entity_id=run_id,
        payload={
            "before_status": "approved", "after_status": "locked",
            "reason_code": body.reason_code,
            "locked_at": locked_at,
            "snapshot_ids": snapshot_ids,
        },
        request_id=request_id,
    )

    record = payroll_db.get_pay_run(org_id, run_id)
    return {"status": "ok", "data": record, "snapshot_ids": snapshot_ids, "request_id": request_id}


# =============================================================================
# 5. TAXES
# =============================================================================

@router.post("/tax-withholdings")
async def create_tax_withholding(
    body: TaxWithholdingCreateRequest,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
) -> Dict[str, Any]:
    request_id = _get_request_id(request)
    org_id = ctx["org_id"]
    tax_id = _new_id()

    payroll_db.create_tax_withholding(
        id=tax_id, org_id=org_id, person_id=body.person_id,
        tax_type=body.tax_type, rate=body.rate,
        effective_date=body.effective_date,
        filing_status=body.filing_status, allowances=body.allowances,
    )

    _audit_or_abort(
        actor=ctx["user_id"], action="payroll_tax_withholding_created",
        entity="payroll_tax_withholdings", entity_id=tax_id,
        payload={"person_id": body.person_id, "tax_type": body.tax_type, "rate": body.rate},
        request_id=request_id,
    )

    return {"status": "ok", "data": {"id": tax_id}, "request_id": request_id}


@router.get("/tax-withholdings")
async def list_tax_withholdings(
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    person_id: Optional[str] = Query(default=None),
    limit: int = Query(default=100, le=500),
) -> Dict[str, Any]:
    request_id = _get_request_id(request)
    items = payroll_db.list_tax_withholdings(ctx["org_id"], person_id=person_id, limit=limit)
    return {"status": "ok", "items": items, "total": len(items), "request_id": request_id}


# =============================================================================
# 6. BENEFITS
# =============================================================================

@router.post("/benefit-enrollments")
async def create_benefit_enrollment(
    body: BenefitEnrollmentCreateRequest,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
) -> Dict[str, Any]:
    request_id = _get_request_id(request)
    org_id = ctx["org_id"]
    enrollment_id = _new_id()

    payroll_db.create_benefit_enrollment(
        id=enrollment_id, org_id=org_id, person_id=body.person_id,
        benefit_type=body.benefit_type.value, plan_name=body.plan_name,
        employee_contribution=body.employee_contribution,
        employer_contribution=body.employer_contribution,
        effective_date=body.effective_date, end_date=body.end_date,
    )

    _audit_or_abort(
        actor=ctx["user_id"], action="payroll_benefit_enrollment_created",
        entity="payroll_benefit_enrollments", entity_id=enrollment_id,
        payload={"person_id": body.person_id, "benefit_type": body.benefit_type.value, "plan_name": body.plan_name},
        request_id=request_id,
    )

    return {"status": "ok", "data": {"id": enrollment_id}, "request_id": request_id}


@router.get("/benefit-enrollments")
async def list_benefit_enrollments(
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    person_id: Optional[str] = Query(default=None),
    limit: int = Query(default=100, le=500),
) -> Dict[str, Any]:
    request_id = _get_request_id(request)
    items = payroll_db.list_benefit_enrollments(ctx["org_id"], person_id=person_id, limit=limit)
    return {"status": "ok", "items": items, "total": len(items), "request_id": request_id}


# =============================================================================
# 7. ACCOUNTING (Journal Entries)
# =============================================================================

@router.post("/journal-entries")
async def create_journal_entry(
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    pay_run_id: str = Query(...),
    account_code: str = Query(...),
    debit: float = Query(..., ge=0),
    credit: float = Query(..., ge=0),
    description: str = Query(...),
    cost_code: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    request_id = _get_request_id(request)
    org_id = ctx["org_id"]
    entry_id = _new_id()

    payroll_db.create_journal_entry(
        id=entry_id, org_id=org_id, pay_run_id=pay_run_id,
        account_code=account_code, debit=debit, credit=credit,
        description=description, cost_code=cost_code,
    )

    _audit_or_abort(
        actor=ctx["user_id"], action="payroll_journal_entry_created",
        entity="payroll_journal_entries", entity_id=entry_id,
        payload={"pay_run_id": pay_run_id, "account_code": account_code, "debit": debit, "credit": credit},
        request_id=request_id,
    )

    return {"status": "ok", "data": {"id": entry_id}, "request_id": request_id}


@router.get("/journal-entries")
async def list_journal_entries(
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    pay_run_id: Optional[str] = Query(default=None),
    limit: int = Query(default=200, le=1000),
) -> Dict[str, Any]:
    request_id = _get_request_id(request)
    items = payroll_db.list_journal_entries(ctx["org_id"], pay_run_id=pay_run_id, limit=limit)
    return {"status": "ok", "items": items, "total": len(items), "request_id": request_id}


# =============================================================================
# 8. COMPLIANCE CHECKS
# =============================================================================

@router.get("/compliance-checks")
async def list_compliance_checks(
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    pay_run_id: str = Query(...),
) -> Dict[str, Any]:
    request_id = _get_request_id(request)
    items = payroll_db.list_compliance_checks(ctx["org_id"], pay_run_id)
    return {"status": "ok", "items": items, "total": len(items), "request_id": request_id}


# =============================================================================
# 9. AUDIT (read-only — queries the audit log for payroll events)
# =============================================================================

@router.get("/audit-log")
async def get_payroll_audit_log(
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    entity: Optional[str] = Query(default=None, description="Filter by entity type (e.g. payroll_people)"),
    entity_id: Optional[str] = Query(default=None, description="Filter by entity ID"),
    limit: int = Query(default=100, le=500),
) -> Dict[str, Any]:
    """
    Read-only access to payroll audit events.

    Queries the central audit_events table filtered to payroll-related actions.
    """
    from app.db import get_db_connection
    import sqlite3

    request_id = _get_request_id(request)
    org_id = ctx["org_id"]

    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    try:
        conditions = ["organization_id = ?", "action LIKE 'payroll_%'"]
        params: list = [org_id]

        if entity:
            conditions.append("entity = ?")
            params.append(entity)
        if entity_id:
            conditions.append("entity_id = ?")
            params.append(entity_id)

        params.append(limit)
        where = " AND ".join(conditions)

        rows = conn.execute(
            f"SELECT * FROM audit_events WHERE {where} ORDER BY created_at DESC LIMIT ?",
            tuple(params),
        ).fetchall()
        items = [dict(r) for r in rows]
    except Exception:
        items = []
    finally:
        conn.close()

    return {"status": "ok", "items": items, "total": len(items), "request_id": request_id}


# =============================================================================
# 10. SNAPSHOTS (read-only)
# =============================================================================

@router.get("/snapshots")
async def list_snapshots(
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    snapshot_type: Optional[str] = Query(default=None),
    pay_run_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, le=200),
) -> Dict[str, Any]:
    request_id = _get_request_id(request)
    items = payroll_db.list_snapshots(
        ctx["org_id"], snapshot_type=snapshot_type,
        pay_run_id=pay_run_id, limit=limit,
    )
    return {"status": "ok", "items": items, "total": len(items), "request_id": request_id}


@router.get("/snapshots/{snapshot_id}")
async def get_snapshot(
    snapshot_id: str,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
) -> Dict[str, Any]:
    request_id = _get_request_id(request)
    record = payroll_db.get_snapshot(ctx["org_id"], snapshot_id)
    if not record:
        _not_found("Snapshot", snapshot_id, request_id)

    # Parse data JSON for response
    data = record.get("data")
    if isinstance(data, str):
        try:
            record["data"] = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            pass

    return {"status": "ok", "data": record, "request_id": request_id}
