from fastapi import APIRouter
from pydantic import BaseModel
from app.reconai_core.veteran_tracker import VeteranTracker

router = APIRouter(prefix="/api/veteran", tags=["veteran"])

class VeteranProfile(BaseModel):
    dd214_data: dict
    business_name: str
    veteran_ownership: float = 1.0

@router.post("/setup-profile")
async def setup_veteran_profile(profile: VeteranProfile):
    """Setup veteran business profile"""
    tracker = VeteranTracker(
        dd214_data=profile.dd214_data,
        business_name=profile.business_name,
        veteran_ownership_percent=profile.veteran_ownership
    )
    
    va_disability = tracker.calculate_va_disability_amount()
    
    return {
        "status": "created",
        "certifications": tracker.certifications,
        "va_disability": va_disability
    }

@router.post("/check-eligibility")
async def check_grant_eligibility(
    veteran_profile: VeteranProfile,
    grant_program: str
):
    """Check eligibility for veteran grant"""
    tracker = VeteranTracker(
        dd214_data=veteran_profile.dd214_data,
        business_name=veteran_profile.business_name
    )
    
    return tracker.verify_eligibility(grant_program)

@router.get("/grant-programs")
async def list_grant_programs():
    """List available veteran grant programs"""
    return {
        "programs": [
            {"id": "streetshares", "name": "StreetShares", "max": 100000},
            {"id": "fedex_veteran", "name": "FedEx Grant", "max": 50000},
            {"id": "vwise", "name": "V-WISE", "max": 0},
            {"id": "hivers_strivers", "name": "Hivers & Strivers", "max": 250000}
        ]
    }