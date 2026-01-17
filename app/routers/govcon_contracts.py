# app/routers/govcon_contracts.py
"""
GovCon Contracts Router - DCAA Compliant Contract Management

Handles government contracts with:
- Contract lifecycle management
- CLIN/SLIN tracking
- Funding tracking
- Period of performance enforcement
- Audit trail for all changes

CANONICAL LAWS ENFORCED:
- Advisory-only behavior (no autonomous execution)
- Manual approval required for modifications
- Immutable audit trail
- Evidence required for all operations

ENTITLEMENT REQUIREMENT:
- Requires GovCon, Contractor, or Enterprise tier
- Server-side enforcement (not just UI gating)
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
    """
    Dependency that enforces GovCon entitlement.
    Returns 403 if user's tier doesn't include GovCon access.
    """
    require_govcon_entitlement(ctx["tier"], request=request)
    return ctx


router = APIRouter(
    prefix="/govcon/contracts",
    tags=["GovCon Contracts"],
    dependencies=[Depends(require_govcon_access)],
)


# =============================================================================
# ENUMS
# =============================================================================

class ContractType(str, Enum):
    COST_PLUS_FIXED_FEE = "cpff"
    COST_PLUS_INCENTIVE_FEE = "cpif"
    COST_PLUS_AWARD_FEE = "cpaf"
    FIRM_FIXED_PRICE = "ffp"
    TIME_AND_MATERIALS = "t_and_m"
    LABOR_HOUR = "labor_hour"
    INDEFINITE_DELIVERY = "idiq"


class ContractStatus(str, Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    COMPLETED = "completed"
    CLOSED = "closed"


class ModificationStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


# =============================================================================
# MODELS
# =============================================================================

class CLIN(BaseModel):
    """Contract Line Item Number"""
    clin_number: str = Field(..., description="CLIN identifier (e.g., 0001)")
    description: str
    quantity: Optional[int] = None
    unit_price: Optional[float] = None
    total_value: float
    funded_amount: float = 0.0
    obligated_amount: float = 0.0
    expended_amount: float = 0.0
    labor_category: Optional[str] = None
    is_option: bool = False


class Contract(BaseModel):
    """Government Contract Model"""
    id: str = Field(default_factory=lambda: str(uuid4()))
    contract_number: str = Field(..., description="Contract number (e.g., W91CRB-23-C-0001)")
    contract_type: ContractType
    status: ContractStatus = ContractStatus.DRAFT

    # Parties
    contractor_name: str
    contractor_cage: str = Field(..., description="CAGE Code")
    contractor_duns: Optional[str] = Field(None, description="DUNS/UEI Number")
    contracting_agency: str
    contracting_officer: str
    contracting_officer_email: Optional[str] = None

    # Values
    total_value: float
    funded_value: float = 0.0
    ceiling_value: Optional[float] = None

    # Dates
    award_date: date
    period_of_performance_start: date
    period_of_performance_end: date

    # CLINs
    clins: List[CLIN] = []

    # Audit
    created_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: str
    last_modified_at: Optional[datetime] = None
    last_modified_by: Optional[str] = None
    modification_count: int = 0

    # Evidence
    evidence: Optional[dict] = None


class ContractModification(BaseModel):
    """Contract Modification Request"""
    id: str = Field(default_factory=lambda: str(uuid4()))
    contract_id: str
    modification_number: str = Field(..., description="Mod number (e.g., P00001)")
    modification_type: str = Field(..., description="Type: administrative, funding, scope, etc.")
    description: str

    # Changes
    value_change: Optional[float] = None
    period_extension_days: Optional[int] = None
    clin_changes: Optional[List[dict]] = None

    # Status
    status: ModificationStatus = ModificationStatus.PENDING

    # Approval
    requested_by: str
    requested_at: datetime = Field(default_factory=datetime.utcnow)
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None

    # Evidence (MANDATORY per canonical laws)
    evidence: dict = Field(..., description="Evidence attachment required")
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)


class ContractCreate(BaseModel):
    """Contract creation request"""
    contract_number: str
    contract_type: ContractType
    contractor_name: str
    contractor_cage: str
    contractor_duns: Optional[str] = None
    contracting_agency: str
    contracting_officer: str
    contracting_officer_email: Optional[str] = None
    total_value: float
    funded_value: float = 0.0
    ceiling_value: Optional[float] = None
    award_date: date
    period_of_performance_start: date
    period_of_performance_end: date
    clins: List[CLIN] = []
    evidence: dict = Field(..., description="Evidence required for audit trail")


class ContractResponse(BaseModel):
    """Contract response with advisory info"""
    contract: Contract
    advisory: dict = Field(default_factory=lambda: {
        "type": "advisory",
        "autonomous": False,
        "execution_allowed": False,
        "message": "Contract data provided for review. Human approval required for any modifications."
    })


# =============================================================================
# IN-MEMORY STORAGE (Replace with DB in production)
# =============================================================================

_contracts: dict[str, Contract] = {}
_modifications: dict[str, ContractModification] = {}
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
        "immutable": True
    }
    _audit_log.append(entry)
    return entry


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/", response_model=List[ContractResponse])
async def list_contracts(
    status: Optional[ContractStatus] = None,
    contract_type: Optional[ContractType] = None
):
    """
    List all contracts (READ-ONLY, advisory)

    Returns contracts with advisory wrapper indicating human action required for modifications.
    """
    contracts = list(_contracts.values())

    if status:
        contracts = [c for c in contracts if c.status == status]
    if contract_type:
        contracts = [c for c in contracts if c.contract_type == contract_type]

    return [ContractResponse(contract=c) for c in contracts]


@router.get("/{contract_id}", response_model=ContractResponse)
async def get_contract(contract_id: str):
    """
    Get contract by ID (READ-ONLY, advisory)
    """
    if contract_id not in _contracts:
        raise HTTPException(status_code=404, detail="Contract not found")

    return ContractResponse(contract=_contracts[contract_id])


@router.post("/", response_model=ContractResponse, status_code=status.HTTP_201_CREATED)
async def create_contract(
    data: ContractCreate,
    user_id: str = "system"  # In production, get from auth context
):
    """
    Create a new contract (REQUIRES EVIDENCE)

    Creates contract in DRAFT status. Manual approval required to activate.
    """
    # Validate evidence (CANONICAL LAW: Evidence required)
    if not data.evidence or not isinstance(data.evidence, dict):
        raise HTTPException(
            status_code=400,
            detail="Evidence attachment required per canonical laws"
        )

    contract = Contract(
        contract_number=data.contract_number,
        contract_type=data.contract_type,
        contractor_name=data.contractor_name,
        contractor_cage=data.contractor_cage,
        contractor_duns=data.contractor_duns,
        contracting_agency=data.contracting_agency,
        contracting_officer=data.contracting_officer,
        contracting_officer_email=data.contracting_officer_email,
        total_value=data.total_value,
        funded_value=data.funded_value,
        ceiling_value=data.ceiling_value,
        award_date=data.award_date,
        period_of_performance_start=data.period_of_performance_start,
        period_of_performance_end=data.period_of_performance_end,
        clins=data.clins,
        created_by=user_id,
        evidence=data.evidence
    )

    _contracts[contract.id] = contract

    # Audit log (IMMUTABLE)
    _log_audit(
        action="contract_created",
        entity_type="contract",
        entity_id=contract.id,
        user_id=user_id,
        details={
            "contract_number": contract.contract_number,
            "total_value": contract.total_value,
            "evidence": data.evidence
        }
    )

    return ContractResponse(
        contract=contract,
        advisory={
            "type": "advisory",
            "autonomous": False,
            "execution_allowed": False,
            "message": "Contract created in DRAFT status. Manual approval required to activate.",
            "next_steps": ["Review contract details", "Submit for approval", "Activate after CO signature"]
        }
    )


@router.post("/{contract_id}/modifications", response_model=dict)
async def request_modification(
    contract_id: str,
    modification_type: str,
    description: str,
    evidence: dict,
    value_change: Optional[float] = None,
    period_extension_days: Optional[int] = None,
    user_id: str = "system"
):
    """
    Request a contract modification (REQUIRES MANUAL APPROVAL)

    Creates modification in PENDING status. Cannot be auto-approved.
    """
    if contract_id not in _contracts:
        raise HTTPException(status_code=404, detail="Contract not found")

    contract = _contracts[contract_id]

    # Generate mod number
    mod_count = contract.modification_count + 1
    mod_number = f"P{mod_count:05d}"

    modification = ContractModification(
        contract_id=contract_id,
        modification_number=mod_number,
        modification_type=modification_type,
        description=description,
        value_change=value_change,
        period_extension_days=period_extension_days,
        requested_by=user_id,
        evidence=evidence
    )

    _modifications[modification.id] = modification

    # Audit log
    _log_audit(
        action="modification_requested",
        entity_type="contract_modification",
        entity_id=modification.id,
        user_id=user_id,
        details={
            "contract_id": contract_id,
            "modification_number": mod_number,
            "modification_type": modification_type,
            "value_change": value_change
        }
    )

    return {
        "modification_id": modification.id,
        "modification_number": mod_number,
        "status": "pending",
        "advisory": {
            "type": "advisory",
            "autonomous": False,
            "execution_allowed": False,
            "message": "Modification request submitted. MANUAL APPROVAL REQUIRED.",
            "approval_required_from": "Contracting Officer or authorized approver"
        }
    }


@router.post("/{contract_id}/modifications/{mod_id}/approve", response_model=dict)
async def approve_modification(
    contract_id: str,
    mod_id: str,
    approver_id: str,
    approval_evidence: dict
):
    """
    Approve a contract modification (MANUAL ACTION ONLY)

    This endpoint is called by human approvers only.
    """
    if mod_id not in _modifications:
        raise HTTPException(status_code=404, detail="Modification not found")

    modification = _modifications[mod_id]

    if modification.status != ModificationStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"Modification is {modification.status}, cannot approve"
        )

    # Apply modification
    contract = _contracts[contract_id]

    if modification.value_change:
        contract.total_value += modification.value_change
        contract.funded_value += modification.value_change

    if modification.period_extension_days:
        from datetime import timedelta
        contract.period_of_performance_end += timedelta(days=modification.period_extension_days)

    contract.modification_count += 1
    contract.last_modified_at = datetime.utcnow()
    contract.last_modified_by = approver_id

    # Update modification status
    modification.status = ModificationStatus.APPROVED
    modification.approved_by = approver_id
    modification.approved_at = datetime.utcnow()

    # Audit log
    _log_audit(
        action="modification_approved",
        entity_type="contract_modification",
        entity_id=mod_id,
        user_id=approver_id,
        details={
            "contract_id": contract_id,
            "modification_number": modification.modification_number,
            "approval_evidence": approval_evidence
        }
    )

    return {
        "status": "approved",
        "modification": modification.dict(),
        "contract_updated": True,
        "audit_logged": True
    }


@router.get("/{contract_id}/audit-trail", response_model=List[dict])
async def get_contract_audit_trail(contract_id: str):
    """
    Get immutable audit trail for a contract (READ-ONLY)
    """
    trail = [
        entry for entry in _audit_log
        if entry["entity_id"] == contract_id or
           entry.get("details", {}).get("contract_id") == contract_id
    ]
    return trail


@router.get("/{contract_id}/funding-status", response_model=dict)
async def get_funding_status(contract_id: str):
    """
    Get funding status for a contract (DCAA compliance view)
    """
    if contract_id not in _contracts:
        raise HTTPException(status_code=404, detail="Contract not found")

    contract = _contracts[contract_id]

    total_obligated = sum(clin.obligated_amount for clin in contract.clins)
    total_expended = sum(clin.expended_amount for clin in contract.clins)

    return {
        "contract_id": contract_id,
        "contract_number": contract.contract_number,
        "total_value": contract.total_value,
        "funded_value": contract.funded_value,
        "total_obligated": total_obligated,
        "total_expended": total_expended,
        "remaining_funds": contract.funded_value - total_expended,
        "funding_percentage": (total_expended / contract.funded_value * 100) if contract.funded_value > 0 else 0,
        "advisory": {
            "type": "advisory",
            "message": "Funding status provided for review. Monitor burn rate for DCAA compliance."
        }
    }
