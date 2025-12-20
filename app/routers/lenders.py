from fastapi import APIRouter
from pydantic import BaseModel
from app.reconai_core.lender_packager import LenderPackager
import pandas as pd

router = APIRouter(prefix="/api/lender", tags=["lender"])

class PackageRequest(BaseModel):
    lender: str
    expenses: list[dict]
    revenue: list[dict] = []
    business_info: dict
    owner_info: dict = {}
    debts: list[dict] = []

@router.post("/create-package")
async def create_package(request: PackageRequest):
    """Generate lender-specific loan package"""
    packager = LenderPackager(lender=request.lender)
    
    financial_data = {
        'expenses_df': pd.DataFrame(request.expenses),
        'revenue_df': pd.DataFrame(request.revenue),
        'business_info': request.business_info,
        'owner_info': request.owner_info,
        'debts': request.debts
    }
    
    package = packager.create_package(financial_data)
    validation = packager.validate_package(package)
    
    return {
        "package": package,
        "validation": {
            "is_complete": validation.is_complete,
            "missing_items": validation.missing_items,
            "completeness_score": validation.completeness_score
        }
    }

@router.get("/lenders")
async def list_lenders():
    """List available lender profiles"""
    return {
        "lenders": [
            {"id": "sba_7a", "name": "SBA 7(a) Standard", "max": 5000000},
            {"id": "sba_express", "name": "SBA Express", "max": 500000},
            {"id": "streetshares", "name": "StreetShares", "max": 250000},
            {"id": "fedex_grant", "name": "FedEx Grant", "max": 50000}
        ]
    }