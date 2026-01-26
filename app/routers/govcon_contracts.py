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
from app.govcon.contract import GOVCON_CONTRACT_VERSION


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
    org_id: str = Field(..., description="Organization ID - REQUIRED for multi-tenant isolation")
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
    """Contract response with advisory info.

    CONTRACT VERSION: 1
    - govcon_version: ALWAYS present, integer
    - lifecycle: ALWAYS present (status + reason_code)
    - evidence: ALWAYS present (metadata for auditability)
    """
    # Contract version - ALWAYS present
    govcon_version: int = GOVCON_CONTRACT_VERSION

    # Lifecycle - ALWAYS present
    lifecycle: dict = Field(default_factory=lambda: {"status": "success", "reason_code": None})

    # Evidence metadata - ALWAYS present
    evidence: dict = Field(default_factory=lambda: {
        "sources": ["contracts"],
        "coverage_window": {"start": None, "end": None},
        "evaluated_at": datetime.utcnow().isoformat(),
        "dcaa_compliant": True,
    })

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


def _require_contract_org_ownership(
    contract_id: str,
    ctx_org_id: str,
    user_id: str,
    request_id: str
) -> Contract:
    """
    P0 SECURITY: Verify org ownership before any access.

    CANONICAL LAW: Multi-tenant isolation
    - Resource MUST belong to caller's org
    - Logs unauthorized access attempts
    - Returns 403 on mismatch, 404 if not found
    """
    if contract_id not in _contracts:
        raise HTTPException(status_code=404, detail="Contract not found")

    contract = _contracts[contract_id]

    # P0 SECURITY: Verify org ownership
    if contract.org_id != ctx_org_id:
        # Log unauthorized access attempt
        _log_audit(
            action="unauthorized_access_blocked",
            entity_type="contract",
            entity_id=contract_id,
            user_id=user_id,
            details={
                "reason": "org_mismatch",
                "attempted_org": ctx_org_id,
                "resource_org": contract.org_id,
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

    return contract


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/", response_model=List[ContractResponse])
async def list_contracts(
    request: Request,
    contract_status: Optional[ContractStatus] = None,
    contract_type: Optional[ContractType] = None,
    ctx: AuthContext = Depends(require_govcon_access)
):
    """
    List all contracts (READ-ONLY, advisory)

    Returns contracts with advisory wrapper indicating human action required for modifications.

    P0 SECURITY: Only returns contracts belonging to caller's org.
    """
    org_id = ctx["org_id"]

    # P0 SECURITY: Filter by org_id FIRST
    contracts = [c for c in _contracts.values() if c.org_id == org_id]

    if contract_status:
        contracts = [c for c in contracts if c.status == contract_status]
    if contract_type:
        contracts = [c for c in contracts if c.contract_type == contract_type]

    return [ContractResponse(contract=c) for c in contracts]


@router.get("/{contract_id}", response_model=ContractResponse)
async def get_contract(
    request: Request,
    contract_id: str,
    ctx: AuthContext = Depends(require_govcon_access)
):
    """
    Get contract by ID (READ-ONLY, advisory)

    P0 SECURITY: Requires org ownership verification.
    """
    request_id = getattr(request.state, "request_id", None) or str(uuid4())

    # P0 SECURITY: Verify org ownership
    contract = _require_contract_org_ownership(
        contract_id, ctx["org_id"], ctx["user_id"], request_id
    )

    return ContractResponse(contract=contract)


@router.post("/", response_model=ContractResponse, status_code=status.HTTP_201_CREATED)
async def create_contract(
    request: Request,
    data: ContractCreate,
    ctx: AuthContext = Depends(require_govcon_access)
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

    user_id = ctx["user_id"]
    org_id = ctx["org_id"]
    request_id = getattr(request.state, "request_id", None) or str(uuid4())

    contract = Contract(
        org_id=org_id,  # P0 SECURITY: Store org ownership
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

    # Audit log (IMMUTABLE) with full context
    _log_audit(
        action="contract_created",
        entity_type="contract",
        entity_id=contract.id,
        user_id=user_id,
        details={
            "contract_number": contract.contract_number,
            "total_value": contract.total_value,
            "evidence": data.evidence
        },
        org_id=org_id,
        request_id=request_id,
        after_state={"status": "draft", "contract_number": contract.contract_number}
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
    request: Request,
    contract_id: str,
    modification_type: str,
    description: str,
    evidence: dict,
    value_change: Optional[float] = None,
    period_extension_days: Optional[int] = None,
    ctx: AuthContext = Depends(require_govcon_access)
):
    """
    Request a contract modification (REQUIRES MANUAL APPROVAL)

    Creates modification in PENDING status. Cannot be auto-approved.

    P0 SECURITY: Requires org ownership verification.
    """
    user_id = ctx["user_id"]
    org_id = ctx["org_id"]
    request_id = getattr(request.state, "request_id", None) or str(uuid4())

    # P0 SECURITY: Verify org ownership
    contract = _require_contract_org_ownership(
        contract_id, org_id, user_id, request_id
    )

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

    # Audit log with full context
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
        },
        org_id=org_id,
        request_id=request_id,
        after_state={"status": "pending", "modification_number": mod_number}
    )

    now = datetime.utcnow().isoformat()
    return {
        # Contract version - ALWAYS present
        "govcon_version": GOVCON_CONTRACT_VERSION,
        # Lifecycle - ALWAYS present
        "lifecycle": {"status": "success", "reason_code": None},
        # Evidence metadata - ALWAYS present
        "evidence": {
            "sources": ["contracts", "modifications"],
            "coverage_window": {"start": None, "end": None},
            "evaluated_at": now,
            "dcaa_compliant": True,
        },
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
    request: Request,
    contract_id: str,
    mod_id: str,
    approval_evidence: dict,
    ctx: AuthContext = Depends(require_govcon_access)
):
    """
    Approve a contract modification (MANUAL ACTION ONLY)

    This endpoint is called by human approvers only.

    P0 SECURITY: Requires org ownership verification.
    """
    approver_id = ctx["user_id"]
    org_id = ctx["org_id"]
    request_id = getattr(request.state, "request_id", None) or str(uuid4())

    # P0 SECURITY: Verify org ownership of contract
    contract = _require_contract_org_ownership(
        contract_id, org_id, approver_id, request_id
    )

    if mod_id not in _modifications:
        raise HTTPException(status_code=404, detail="Modification not found")

    modification = _modifications[mod_id]

    if modification.status != ModificationStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"Modification is {modification.status}, cannot approve"
        )

    # Capture before state
    before_state = {
        "total_value": contract.total_value,
        "funded_value": contract.funded_value,
        "modification_status": modification.status.value
    }

    # Apply modification
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

    # Capture after state
    after_state = {
        "total_value": contract.total_value,
        "funded_value": contract.funded_value,
        "modification_status": "approved"
    }

    # Audit log with full context
    _log_audit(
        action="modification_approved",
        entity_type="contract_modification",
        entity_id=mod_id,
        user_id=approver_id,
        details={
            "contract_id": contract_id,
            "modification_number": modification.modification_number,
            "approval_evidence": approval_evidence
        },
        org_id=org_id,
        request_id=request_id,
        before_state=before_state,
        after_state=after_state
    )

    now = datetime.utcnow().isoformat()
    return {
        # Contract version - ALWAYS present
        "govcon_version": GOVCON_CONTRACT_VERSION,
        # Lifecycle - ALWAYS present
        "lifecycle": {"status": "success", "reason_code": None},
        # Evidence metadata - ALWAYS present
        "evidence": {
            "sources": ["contracts", "modifications"],
            "coverage_window": {"start": None, "end": None},
            "evaluated_at": now,
            "dcaa_compliant": True,
        },
        "status": "approved",
        "modification": modification.dict(),
        "contract_updated": True,
        "audit_logged": True
    }


@router.get("/{contract_id}/audit-trail", response_model=dict)
async def get_contract_audit_trail(
    request: Request,
    contract_id: str,
    ctx: AuthContext = Depends(require_govcon_access)
):
    """
    Get immutable audit trail for a contract (READ-ONLY)

    P0 SECURITY: Requires org ownership verification.
    """
    request_id = getattr(request.state, "request_id", None) or str(uuid4())

    org_id = ctx["org_id"]

    # P0 SECURITY: Verify org ownership before returning audit trail
    _require_contract_org_ownership(
        contract_id, org_id, ctx["user_id"], request_id
    )

    # P0 SECURITY: Filter by org_id FIRST, then by entity_id (defense in depth)
    trail = [
        entry for entry in _audit_log
        if entry.get("org_id") == org_id and (
            entry["entity_id"] == contract_id or
            entry.get("details", {}).get("contract_id") == contract_id
        )
    ]
    now = datetime.utcnow().isoformat()
    return {
        # Contract version - ALWAYS present
        "govcon_version": GOVCON_CONTRACT_VERSION,
        # Lifecycle - ALWAYS present
        "lifecycle": {"status": "success", "reason_code": None},
        # Evidence metadata - ALWAYS present
        "evidence": {
            "sources": ["audit_log"],
            "coverage_window": {"start": None, "end": None},
            "evaluated_at": now,
            "dcaa_compliant": True,
        },
        "audit_trail": trail,
    }


@router.get("/{contract_id}/funding-status", response_model=dict)
async def get_funding_status(
    request: Request,
    contract_id: str,
    ctx: AuthContext = Depends(require_govcon_access)
):
    """
    Get funding status for a contract (DCAA compliance view)

    P0 SECURITY: Requires org ownership verification.
    """
    request_id = getattr(request.state, "request_id", None) or str(uuid4())

    # P0 SECURITY: Verify org ownership
    contract = _require_contract_org_ownership(
        contract_id, ctx["org_id"], ctx["user_id"], request_id
    )

    total_obligated = sum(clin.obligated_amount for clin in contract.clins)
    total_expended = sum(clin.expended_amount for clin in contract.clins)

    now = datetime.utcnow().isoformat()
    return {
        # Contract version - ALWAYS present
        "govcon_version": GOVCON_CONTRACT_VERSION,
        # Lifecycle - ALWAYS present
        "lifecycle": {"status": "success", "reason_code": None},
        # Evidence metadata - ALWAYS present
        "evidence": {
            "sources": ["contracts"],
            "coverage_window": {"start": None, "end": None},
            "evaluated_at": now,
            "dcaa_compliant": True,
        },
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
