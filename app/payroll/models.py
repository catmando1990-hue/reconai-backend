# app/payroll/models.py
"""
Payroll Domain — Pydantic Models

Covers all 10 sub-domains:
  people, compensation, time_labor, pay_runs,
  taxes, benefits, accounting, compliance, audit, snapshots

CANONICAL LAWS:
- All response models are frozen (immutable after creation)
- All fields explicitly typed
- Validation at boundaries
- No compliance claims
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# =============================================================================
# ENUMS
# =============================================================================

class PayRunStatus(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    LOCKED = "locked"


class EmployeeStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    TERMINATED = "terminated"


class CompensationType(str, Enum):
    SALARY = "salary"
    HOURLY = "hourly"
    CONTRACT = "contract"


class TimeEntryStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class BenefitType(str, Enum):
    HEALTH = "health"
    DENTAL = "dental"
    VISION = "vision"
    RETIREMENT_401K = "retirement_401k"
    HSA = "hsa"
    LIFE = "life"
    DISABILITY = "disability"
    OTHER = "other"


class SnapshotType(str, Enum):
    PAYROLL = "payroll"
    LABOR_DISTRIBUTION = "labor_distribution"
    TAX_LIABILITY = "tax_liability"


# =============================================================================
# SUB-DOMAIN: PEOPLE
# =============================================================================

class PersonCreateRequest(BaseModel):
    """Request to create a person/employee record."""
    employee_id: str = Field(..., description="External employee identifier")
    first_name: str = Field(..., min_length=1)
    last_name: str = Field(..., min_length=1)
    email: Optional[str] = None
    department: Optional[str] = None
    job_title: Optional[str] = None
    hire_date: str = Field(..., description="ISO date YYYY-MM-DD")
    status: EmployeeStatus = EmployeeStatus.ACTIVE


class PersonUpdateRequest(BaseModel):
    """Request to update a person record. Requires reason_code."""
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    department: Optional[str] = None
    job_title: Optional[str] = None
    status: Optional[EmployeeStatus] = None
    reason_code: str = Field(..., min_length=1, description="Reason for edit (audit requirement)")


class PersonRecord(BaseModel):
    """Person/employee record response."""
    id: str
    organization_id: str
    employee_id: str
    first_name: str
    last_name: str
    email: Optional[str]
    department: Optional[str]
    job_title: Optional[str]
    hire_date: str
    status: str
    created_at: str
    updated_at: str

    class Config:
        frozen = True


# =============================================================================
# SUB-DOMAIN: COMPENSATION
# =============================================================================

class CompensationCreateRequest(BaseModel):
    """Request to create a compensation record."""
    person_id: str = Field(..., description="Internal person record ID")
    comp_type: CompensationType
    rate: float = Field(..., gt=0, description="Pay rate (annual salary or hourly rate)")
    currency: str = Field(default="USD", max_length=3)
    effective_date: str = Field(..., description="ISO date YYYY-MM-DD")
    end_date: Optional[str] = Field(default=None, description="ISO date YYYY-MM-DD or null for current")


class CompensationUpdateRequest(BaseModel):
    """Request to update compensation. Requires reason_code."""
    rate: Optional[float] = Field(default=None, gt=0)
    end_date: Optional[str] = None
    reason_code: str = Field(..., min_length=1)


class CompensationRecord(BaseModel):
    """Compensation record response."""
    id: str
    organization_id: str
    person_id: str
    comp_type: str
    rate: float
    currency: str
    effective_date: str
    end_date: Optional[str]
    created_at: str
    updated_at: str

    class Config:
        frozen = True


# =============================================================================
# SUB-DOMAIN: TIME & LABOR
# =============================================================================

class TimeEntryCreateRequest(BaseModel):
    """Request to create a time/labor entry."""
    person_id: str
    work_date: str = Field(..., description="ISO date YYYY-MM-DD")
    hours: float = Field(..., gt=0, le=24)
    cost_code: Optional[str] = Field(default=None, description="Project/cost code for labor distribution")
    description: Optional[str] = None


class TimeEntryUpdateRequest(BaseModel):
    """Request to update a time entry. Requires reason_code."""
    hours: Optional[float] = Field(default=None, gt=0, le=24)
    cost_code: Optional[str] = None
    description: Optional[str] = None
    status: Optional[TimeEntryStatus] = None
    reason_code: str = Field(..., min_length=1)


class TimeEntryRecord(BaseModel):
    """Time/labor entry response."""
    id: str
    organization_id: str
    person_id: str
    work_date: str
    hours: float
    cost_code: Optional[str]
    description: Optional[str]
    status: str
    created_at: str
    updated_at: str

    class Config:
        frozen = True


# =============================================================================
# SUB-DOMAIN: PAY RUNS
# =============================================================================

class PayRunCreateRequest(BaseModel):
    """Request to create a pay run."""
    pay_period_start: str = Field(..., description="ISO date YYYY-MM-DD")
    pay_period_end: str = Field(..., description="ISO date YYYY-MM-DD")
    description: Optional[str] = None


class PayRunLineItem(BaseModel):
    """A single line item within a pay run."""
    person_id: str
    gross_amount: float = Field(..., ge=0)
    tax_amount: float = Field(..., ge=0)
    benefits_amount: float = Field(..., ge=0)
    deductions_amount: float = Field(..., ge=0)
    net_amount: float = Field(..., ge=0)
    hours_worked: Optional[float] = Field(default=None, ge=0)
    cost_code: Optional[str] = None

    class Config:
        frozen = True


class PayRunAddLineRequest(BaseModel):
    """Request to add a line item to a pay run."""
    person_id: str
    gross_amount: float = Field(..., ge=0)
    tax_amount: float = Field(..., ge=0)
    benefits_amount: float = Field(..., ge=0)
    deductions_amount: float = Field(..., ge=0)
    net_amount: float = Field(..., ge=0)
    hours_worked: Optional[float] = Field(default=None, ge=0)
    cost_code: Optional[str] = None


class PayRunApproveRequest(BaseModel):
    """Request to approve a pay run (draft → approved)."""
    reason_code: str = Field(default="approved_by_admin", min_length=1)


class PayRunLockRequest(BaseModel):
    """Request to lock a pay run (approved → locked). Irreversible."""
    reason_code: str = Field(default="locked_for_processing", min_length=1)
    generate_snapshots: bool = Field(
        default=True,
        description="Generate immutable snapshots on lock"
    )


class PayRunRecord(BaseModel):
    """Pay run response."""
    id: str
    organization_id: str
    pay_period_start: str
    pay_period_end: str
    description: Optional[str]
    status: str
    line_count: int
    total_gross: float
    total_net: float
    locked_at: Optional[str]
    snapshot_id: Optional[str]
    created_at: str
    updated_at: str

    class Config:
        frozen = True


# =============================================================================
# SUB-DOMAIN: TAXES
# =============================================================================

class TaxWithholdingCreateRequest(BaseModel):
    """Request to create a tax withholding record."""
    person_id: str
    tax_type: str = Field(..., description="e.g. federal_income, state_income, fica_ss, fica_medicare")
    rate: float = Field(..., ge=0, le=1, description="Tax rate as decimal (0.22 = 22%)")
    effective_date: str
    filing_status: Optional[str] = None
    allowances: Optional[int] = Field(default=None, ge=0)


class TaxWithholdingRecord(BaseModel):
    """Tax withholding record response."""
    id: str
    organization_id: str
    person_id: str
    tax_type: str
    rate: float
    effective_date: str
    filing_status: Optional[str]
    allowances: Optional[int]
    created_at: str

    class Config:
        frozen = True


# =============================================================================
# SUB-DOMAIN: BENEFITS
# =============================================================================

class BenefitEnrollmentCreateRequest(BaseModel):
    """Request to enroll a person in a benefit."""
    person_id: str
    benefit_type: BenefitType
    plan_name: str = Field(..., min_length=1)
    employee_contribution: float = Field(..., ge=0, description="Per-period employee amount")
    employer_contribution: float = Field(..., ge=0, description="Per-period employer amount")
    effective_date: str
    end_date: Optional[str] = None


class BenefitEnrollmentRecord(BaseModel):
    """Benefit enrollment response."""
    id: str
    organization_id: str
    person_id: str
    benefit_type: str
    plan_name: str
    employee_contribution: float
    employer_contribution: float
    effective_date: str
    end_date: Optional[str]
    created_at: str

    class Config:
        frozen = True


# =============================================================================
# SUB-DOMAIN: ACCOUNTING
# =============================================================================

class PayrollJournalEntryRecord(BaseModel):
    """Payroll journal entry for GL integration."""
    id: str
    organization_id: str
    pay_run_id: str
    account_code: str
    debit: float
    credit: float
    description: str
    cost_code: Optional[str]
    created_at: str

    class Config:
        frozen = True


# =============================================================================
# SUB-DOMAIN: COMPLIANCE
# =============================================================================

class ComplianceCheckRecord(BaseModel):
    """Compliance check result (advisory, not enforcement)."""
    id: str
    organization_id: str
    pay_run_id: str
    check_type: str
    status: str  # "pass", "warning", "fail"
    message: str
    details: Optional[Dict[str, Any]]
    checked_at: str

    class Config:
        frozen = True


# =============================================================================
# SUB-DOMAIN: SNAPSHOTS (IMMUTABLE, HASH-SEALED)
# =============================================================================

class SnapshotRecord(BaseModel):
    """
    Immutable, hash-sealed snapshot.

    Generated ONLY when pay runs are LOCKED.
    Read-only after creation. Referenced by ID only.
    DCAA endpoints accept snapshot IDs — never live objects.
    """
    id: str
    organization_id: str
    snapshot_type: str
    pay_run_id: str
    version: int
    data_hash: str = Field(..., description="SHA-256 hash of snapshot data")
    data: Dict[str, Any] = Field(..., description="Frozen snapshot payload")
    created_at: str

    class Config:
        frozen = True


# =============================================================================
# GENERIC LIST RESPONSE
# =============================================================================

class PayrollListResponse(BaseModel):
    """Generic list response for payroll endpoints."""
    ok: bool = True
    items: List[Dict[str, Any]]
    total: int
    request_id: str

    class Config:
        frozen = True
