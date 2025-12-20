from fastapi import APIRouter
from pydantic import BaseModel
from app.reconai_core.compliance_monitor import ComplianceMonitor
import pandas as pd
from datetime import datetime

router = APIRouter(prefix="/api/compliance", tags=["compliance"])

class ComplianceCheckRequest(BaseModel):
    expenses: list[dict]
    business_type: str = "Schedule C"

@router.post("/check")
async def check_compliance(request: ComplianceCheckRequest):
    """Generate real-time compliance report"""
    monitor = ComplianceMonitor(business_type=request.business_type)
    expenses_df = pd.DataFrame(request.expenses)
    report = monitor.generate_compliance_report(expenses_df)
    return report

@router.post("/check-per-diem")
async def check_per_diem(
    expense_type: str,
    location: str,
    amount: float,
    date: str
):
    """Check if expense exceeds per-diem limits"""
    monitor = ComplianceMonitor()
    alert = monitor.check_per_diem(
        expense_type=expense_type,
        location=location,
        amount=amount,
        date=datetime.fromisoformat(date)
    )
    
    if alert:
        return {
            "exceeded": True,
            "severity": alert.severity.value,
            "message": alert.message,
            "actions": alert.suggested_actions
        }
    return {"exceeded": False}