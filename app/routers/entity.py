from fastapi import APIRouter
from pydantic import BaseModel
from app.reconai_core.multi_entity import MultiEntityManager

router = APIRouter(prefix="/api/entity", tags=["entity"])

class EntitySetup(BaseModel):
    entity_type: str
    entity_name: str
    owners: list[dict]

@router.post("/setup")
async def setup_entity(request: EntitySetup):
    """Setup multi-entity structure"""
    entity = MultiEntityManager(
        entity_type=request.entity_type,
        entity_name=request.entity_name,
        owners=request.owners
    )
    
    return {
        "status": "created",
        "entity_name": entity.entity_name,
        "owners": [
            {"name": o.name, "ownership": o.ownership_percent}
            for o in entity.owners.values()
        ]
    }

@router.post("/calculate-allocations")
async def calculate_allocations(
    entity_setup: EntitySetup,
    transactions: list[dict],
    tax_year: int
):
    """Calculate income/loss allocations"""
    entity = MultiEntityManager(
        entity_type=entity_setup.entity_type,
        entity_name=entity_setup.entity_name,
        owners=entity_setup.owners
    )
    
    for txn in transactions:
        entity.record_transaction(
            transaction_type=txn.get('type', 'expense'),
            amount=txn['amount'],
            category=txn.get('category', 'General'),
            description=txn.get('description', '')
        )
    
    net_income = entity.ytd_income - entity.ytd_expenses
    allocations = entity.calculate_allocations(net_income)
    
    return {"net_income": net_income, "allocations": allocations}