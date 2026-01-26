# app/routers/govcon_indirects.py
"""
GovCon Indirect Pools Router - DCAA Compliant Indirect Cost Management

Handles indirect cost pools with:
- Overhead pool management
- G&A pool management
- Fringe benefit pools
- Rate calculations
- Allocation bases

DCAA REQUIREMENTS:
- Indirect costs must be consistently allocated
- Pools must be properly segregated
- Rates must be calculated per FAR/DFARS
- Documentation required for all allocations

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
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, date
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
    prefix="/govcon/indirects",
    tags=["GovCon Indirect Costs"],
    dependencies=[Depends(require_govcon_access)],
)


# =============================================================================
# ENUMS
# =============================================================================

class PoolType(str, Enum):
    OVERHEAD = "overhead"
    G_AND_A = "g_and_a"
    FRINGE = "fringe"
    MATERIAL_HANDLING = "material_handling"
    FACILITIES = "facilities"
    OTHER = "other"


class AllocationBase(str, Enum):
    DIRECT_LABOR_DOLLARS = "direct_labor_dollars"
    DIRECT_LABOR_HOURS = "direct_labor_hours"
    TOTAL_COST_INPUT = "total_cost_input"
    VALUE_ADDED = "value_added"
    DIRECT_MATERIAL = "direct_material"
    TOTAL_DIRECT_COSTS = "total_direct_costs"


class RateStatus(str, Enum):
    PROVISIONAL = "provisional"
    PROPOSED = "proposed"
    NEGOTIATED = "negotiated"
    FINAL = "final"


class CostAllowability(str, Enum):
    ALLOWABLE = "allowable"
    UNALLOWABLE = "unallowable"
    PARTIALLY_ALLOWABLE = "partially_allowable"
    PENDING_REVIEW = "pending_review"


# =============================================================================
# MODELS
# =============================================================================

class IndirectCost(BaseModel):
    """Individual indirect cost entry"""
    id: str = Field(default_factory=lambda: str(uuid4()))
    description: str
    amount: float
    period_start: date
    period_end: date
    pool_type: PoolType
    cost_element: str = Field(..., description="Cost element code")
    allowability: CostAllowability = CostAllowability.PENDING_REVIEW
    far_citation: Optional[str] = Field(None, description="FAR cost principle citation")

    # Audit
    recorded_at: datetime = Field(default_factory=datetime.utcnow)
    recorded_by: str
    reviewed_at: Optional[datetime] = None
    reviewed_by: Optional[str] = None


class IndirectPool(BaseModel):
    """Indirect cost pool"""
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    pool_type: PoolType
    allocation_base: AllocationBase
    fiscal_year: int
    description: Optional[str] = None

    # Costs
    total_pool_costs: float = 0.0
    allowable_costs: float = 0.0
    unallowable_costs: float = 0.0

    # Base
    total_base: float = 0.0

    # Rate
    calculated_rate: Optional[float] = None
    rate_status: RateStatus = RateStatus.PROVISIONAL
    negotiated_rate: Optional[float] = None
    dcaa_approved: bool = False

    # Audit
    created_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: str
    last_calculated_at: Optional[datetime] = None


class IndirectRate(BaseModel):
    """Indirect rate record"""
    id: str = Field(default_factory=lambda: str(uuid4()))
    pool_id: str
    pool_type: PoolType
    fiscal_year: int

    # Rates
    provisional_rate: float
    proposed_rate: Optional[float] = None
    negotiated_rate: Optional[float] = None
    final_rate: Optional[float] = None

    # Status
    status: RateStatus = RateStatus.PROVISIONAL

    # Dates
    effective_date: date
    expiration_date: Optional[date] = None

    # DCAA
    dcaa_audit_date: Optional[date] = None
    dcaa_auditor: Optional[str] = None
    dcaa_findings: Optional[str] = None

    # Evidence
    evidence: Optional[dict] = None


class PoolCostEntry(BaseModel):
    """Add cost to pool request"""
    description: str
    amount: float
    cost_element: str
    allowability: CostAllowability = CostAllowability.PENDING_REVIEW
    far_citation: Optional[str] = None
    evidence: dict = Field(..., description="Evidence required")


# =============================================================================
# IN-MEMORY STORAGE
# =============================================================================

_pools: dict[str, IndirectPool] = {}
_costs: dict[str, IndirectCost] = {}
_rates: dict[str, IndirectRate] = {}
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


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/pools", response_model=List[dict])
async def list_pools(
    pool_type: Optional[PoolType] = None,
    fiscal_year: Optional[int] = None
):
    """
    List indirect cost pools (READ-ONLY, advisory)
    """
    pools = list(_pools.values())

    if pool_type:
        pools = [p for p in pools if p.pool_type == pool_type]
    if fiscal_year:
        pools = [p for p in pools if p.fiscal_year == fiscal_year]

    return [
        {
            "pool": p.dict(),
            "advisory": {
                "type": "advisory",
                "autonomous": False,
                "message": "Pool data for review. Rate changes require DCAA approval."
            }
        }
        for p in pools
    ]


@router.get("/pools/{pool_id}", response_model=dict)
async def get_pool(pool_id: str):
    """
    Get indirect pool by ID (READ-ONLY)
    """
    if pool_id not in _pools:
        raise HTTPException(status_code=404, detail="Pool not found")

    pool = _pools[pool_id]

    # Get associated costs
    pool_costs = [c for c in _costs.values() if c.pool_type == pool.pool_type]

    return {
        "pool": pool.dict(),
        "costs": [c.dict() for c in pool_costs],
        "analysis": {
            "allowable_percentage": (pool.allowable_costs / pool.total_pool_costs * 100)
                if pool.total_pool_costs > 0 else 0,
            "unallowable_percentage": (pool.unallowable_costs / pool.total_pool_costs * 100)
                if pool.total_pool_costs > 0 else 0
        },
        "advisory": {
            "type": "advisory",
            "message": "Pool details for DCAA compliance review."
        }
    }


@router.post("/pools", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_pool(
    request: Request,
    name: str,
    pool_type: PoolType,
    allocation_base: AllocationBase,
    fiscal_year: int,
    description: Optional[str] = None,
    ctx: AuthContext = Depends(require_govcon_access)
):
    """
    Create a new indirect cost pool
    """
    user_id = ctx["user_id"]
    org_id = ctx["org_id"]
    request_id = getattr(request.state, "request_id", None) or str(uuid4())

    pool = IndirectPool(
        name=name,
        pool_type=pool_type,
        allocation_base=allocation_base,
        fiscal_year=fiscal_year,
        description=description,
        created_by=user_id
    )

    _pools[pool.id] = pool

    _log_audit(
        action="pool_created",
        entity_type="indirect_pool",
        entity_id=pool.id,
        user_id=user_id,
        details={
            "name": name,
            "pool_type": pool_type.value,
            "allocation_base": allocation_base.value,
            "fiscal_year": fiscal_year
        },
        org_id=org_id,
        request_id=request_id,
        after_state={"name": name, "pool_type": pool_type.value}
    )

    return {
        "pool_id": pool.id,
        "pool_type": pool_type.value,
        "status": "created",
        "advisory": {
            "type": "advisory",
            "message": "Pool created. Add costs and calculate rates for DCAA submission."
        }
    }


@router.post("/pools/{pool_id}/costs", response_model=dict)
async def add_pool_cost(
    request: Request,
    pool_id: str,
    cost: PoolCostEntry,
    period_start: date,
    period_end: date,
    ctx: AuthContext = Depends(require_govcon_access)
):
    """
    Add a cost to an indirect pool (REQUIRES EVIDENCE)
    """
    if pool_id not in _pools:
        raise HTTPException(status_code=404, detail="Pool not found")

    pool = _pools[pool_id]
    user_id = ctx["user_id"]
    org_id = ctx["org_id"]
    request_id = getattr(request.state, "request_id", None) or str(uuid4())

    # Validate evidence (CANONICAL LAW)
    if not cost.evidence or not isinstance(cost.evidence, dict):
        raise HTTPException(
            status_code=400,
            detail="Evidence attachment required per canonical laws"
        )

    # Capture before state
    before_state = {
        "total_pool_costs": pool.total_pool_costs,
        "allowable_costs": pool.allowable_costs
    }

    indirect_cost = IndirectCost(
        description=cost.description,
        amount=cost.amount,
        period_start=period_start,
        period_end=period_end,
        pool_type=pool.pool_type,
        cost_element=cost.cost_element,
        allowability=cost.allowability,
        far_citation=cost.far_citation,
        recorded_by=user_id
    )

    _costs[indirect_cost.id] = indirect_cost

    # Update pool totals
    pool.total_pool_costs += cost.amount
    if cost.allowability == CostAllowability.ALLOWABLE:
        pool.allowable_costs += cost.amount
    elif cost.allowability == CostAllowability.UNALLOWABLE:
        pool.unallowable_costs += cost.amount

    # Capture after state
    after_state = {
        "total_pool_costs": pool.total_pool_costs,
        "allowable_costs": pool.allowable_costs
    }

    _log_audit(
        action="cost_added_to_pool",
        entity_type="indirect_cost",
        entity_id=indirect_cost.id,
        user_id=user_id,
        details={
            "pool_id": pool_id,
            "amount": cost.amount,
            "allowability": cost.allowability.value,
            "evidence": cost.evidence
        },
        org_id=org_id,
        request_id=request_id,
        before_state=before_state,
        after_state=after_state
    )

    return {
        "cost_id": indirect_cost.id,
        "pool_totals": {
            "total_pool_costs": pool.total_pool_costs,
            "allowable_costs": pool.allowable_costs,
            "unallowable_costs": pool.unallowable_costs
        },
        "advisory": {
            "type": "advisory",
            "message": "Cost added to pool. Review allowability classification."
        }
    }


@router.post("/pools/{pool_id}/calculate-rate", response_model=dict)
async def calculate_pool_rate(
    pool_id: str,
    allocation_base_amount: float,
    user_id: str = "system"
):
    """
    Calculate indirect rate for a pool (ADVISORY ONLY)

    Returns calculated rate for review. Does not automatically apply.
    """
    if pool_id not in _pools:
        raise HTTPException(status_code=404, detail="Pool not found")

    pool = _pools[pool_id]

    if allocation_base_amount <= 0:
        raise HTTPException(
            status_code=400,
            detail="Allocation base amount must be positive"
        )

    # Calculate rate using allowable costs only
    calculated_rate = (pool.allowable_costs / allocation_base_amount) * 100

    pool.total_base = allocation_base_amount
    pool.calculated_rate = calculated_rate
    pool.last_calculated_at = datetime.utcnow()

    _log_audit(
        action="rate_calculated",
        entity_type="indirect_pool",
        entity_id=pool_id,
        user_id=user_id,
        details={
            "allowable_costs": pool.allowable_costs,
            "allocation_base": allocation_base_amount,
            "calculated_rate": calculated_rate
        }
    )

    return {
        "pool_id": pool_id,
        "pool_type": pool.pool_type.value,
        "allowable_costs": pool.allowable_costs,
        "allocation_base": allocation_base_amount,
        "calculated_rate": round(calculated_rate, 4),
        "rate_status": "provisional",
        "advisory": {
            "type": "advisory",
            "autonomous": False,
            "execution_allowed": False,
            "message": "Rate calculated for review. DCAA negotiation required for final rate.",
            "next_steps": [
                "Review calculated rate",
                "Prepare rate proposal",
                "Submit to DCAA",
                "Negotiate final rate"
            ]
        }
    }


@router.post("/rates", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_rate_record(
    pool_id: str,
    provisional_rate: float,
    effective_date: date,
    evidence: dict,
    user_id: str = "system"
):
    """
    Create an indirect rate record (REQUIRES EVIDENCE)
    """
    if pool_id not in _pools:
        raise HTTPException(status_code=404, detail="Pool not found")

    pool = _pools[pool_id]

    rate = IndirectRate(
        pool_id=pool_id,
        pool_type=pool.pool_type,
        fiscal_year=pool.fiscal_year,
        provisional_rate=provisional_rate,
        effective_date=effective_date,
        evidence=evidence
    )

    _rates[rate.id] = rate

    _log_audit(
        action="rate_created",
        entity_type="indirect_rate",
        entity_id=rate.id,
        user_id=user_id,
        details={
            "pool_id": pool_id,
            "provisional_rate": provisional_rate,
            "effective_date": effective_date.isoformat(),
            "evidence": evidence
        }
    )

    return {
        "rate_id": rate.id,
        "status": "provisional",
        "advisory": {
            "type": "advisory",
            "message": "Provisional rate recorded. Await DCAA audit for final rate."
        }
    }


@router.get("/rates", response_model=List[dict])
async def list_rates(
    pool_type: Optional[PoolType] = None,
    fiscal_year: Optional[int] = None,
    status: Optional[RateStatus] = None
):
    """
    List indirect rates (READ-ONLY)
    """
    rates = list(_rates.values())

    if pool_type:
        rates = [r for r in rates if r.pool_type == pool_type]
    if fiscal_year:
        rates = [r for r in rates if r.fiscal_year == fiscal_year]
    if status:
        rates = [r for r in rates if r.status == status]

    return [
        {
            "rate": r.dict(),
            "advisory": {
                "type": "advisory",
                "message": "Rate data for DCAA compliance review."
            }
        }
        for r in rates
    ]


@router.post("/costs/{cost_id}/review", response_model=dict)
async def review_cost_allowability(
    cost_id: str,
    allowability: CostAllowability,
    far_citation: str,
    review_notes: str,
    evidence: dict,
    reviewer_id: str = "system"
):
    """
    Review and classify cost allowability (REQUIRES EVIDENCE)

    Per FAR 31.201, costs must be classified as allowable/unallowable.
    """
    if cost_id not in _costs:
        raise HTTPException(status_code=404, detail="Cost not found")

    cost = _costs[cost_id]
    old_allowability = cost.allowability

    cost.allowability = allowability
    cost.far_citation = far_citation
    cost.reviewed_at = datetime.utcnow()
    cost.reviewed_by = reviewer_id

    # Update pool totals if changed
    pool = next((p for p in _pools.values() if p.pool_type == cost.pool_type), None)
    if pool:
        if old_allowability == CostAllowability.ALLOWABLE:
            pool.allowable_costs -= cost.amount
        elif old_allowability == CostAllowability.UNALLOWABLE:
            pool.unallowable_costs -= cost.amount

        if allowability == CostAllowability.ALLOWABLE:
            pool.allowable_costs += cost.amount
        elif allowability == CostAllowability.UNALLOWABLE:
            pool.unallowable_costs += cost.amount

    _log_audit(
        action="cost_allowability_reviewed",
        entity_type="indirect_cost",
        entity_id=cost_id,
        user_id=reviewer_id,
        details={
            "old_allowability": old_allowability.value,
            "new_allowability": allowability.value,
            "far_citation": far_citation,
            "review_notes": review_notes,
            "evidence": evidence
        }
    )

    return {
        "cost_id": cost_id,
        "allowability": allowability.value,
        "far_citation": far_citation,
        "reviewed": True,
        "advisory": {
            "type": "advisory",
            "message": "Allowability reviewed. Pool totals updated."
        }
    }


@router.get("/audit-trail", response_model=List[dict])
async def get_indirect_audit_trail(
    pool_id: Optional[str] = None,
    fiscal_year: Optional[int] = None
):
    """
    Get immutable audit trail for indirect costs (READ-ONLY)
    """
    trail = _audit_log.copy()

    if pool_id:
        trail = [
            e for e in trail
            if e["entity_id"] == pool_id or
               e.get("details", {}).get("pool_id") == pool_id
        ]

    return trail
