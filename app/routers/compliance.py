from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel
from typing import List, Optional, Literal
from app.reconai_core.compliance_monitor import ComplianceMonitor
import pandas as pd
from datetime import datetime

try:
    from .auth import get_current_user_id
except ImportError:
    # Fallback if auth not available
    def get_current_user_id():
        return "system"

router = APIRouter(prefix="/api/compliance", tags=["compliance"])


# =========================================================================
# MODELS FOR FRONTEND COMPATIBILITY
# =========================================================================

class ComplianceIndicator(BaseModel):
    """Compliance indicator"""
    id: str
    name: str
    status: Literal["compliant", "warning", "critical"]
    score: float
    description: str
    last_checked: str


class ComplianceCheckRequest(BaseModel):
    """Compliance check request - supports both old and new format"""
    expenses: Optional[list[dict]] = None  # Old format
    transactions: Optional[list[dict]] = None  # New format from frontend
    business_type: str = "Schedule C"
    compliance_type: str = "dcaa"


class ComplianceCheckResponse(BaseModel):
    """Enhanced compliance check response for frontend"""
    overall_score: float
    overall_status: Literal["compliant", "warning", "critical"]
    indicators: List[ComplianceIndicator]
    total_transactions: int
    compliant_transactions: int
    non_compliant_transactions: int
    recommendations: List[dict]
    # Legacy fields
    report: Optional[dict] = None


@router.post("/check", response_model=ComplianceCheckResponse)
async def check_compliance(
    request: ComplianceCheckRequest,
    current_user_id: Optional[str] = Depends(get_current_user_id)
):
    """
    Generate real-time compliance report

    Supports both old format (expenses) and new format (transactions)
    """
    try:
        # Support both old and new request formats
        data = request.transactions or request.expenses or []

        if not data:
            return ComplianceCheckResponse(
                overall_score=100.0,
                overall_status="compliant",
                indicators=[],
                total_transactions=0,
                compliant_transactions=0,
                non_compliant_transactions=0,
                recommendations=[]
            )

        # Run original compliance check
        monitor = ComplianceMonitor(business_type=request.business_type)
        expenses_df = pd.DataFrame(data)
        report = monitor.generate_compliance_report(expenses_df)

        # Calculate enhanced metrics for frontend
        total_count = len(data)
        compliant_count = 0

        # Check receipt compliance (FAR 31.205-46)
        receipts_required = sum(1 for txn in data if abs(txn.get("amount", 0)) >= 75)
        receipts_missing = sum(
            1 for txn in data
            if abs(txn.get("amount", 0)) >= 75 and not (txn.get("has_receipt") or txn.get("receipt_url"))
        )
        receipt_score = ((receipts_required - receipts_missing) / receipts_required * 100) if receipts_required > 0 else 100

        # Check categorization
        uncategorized = sum(
            1 for txn in data
            if not txn.get("reconai_category") and not txn.get("category")
        )
        categorization_score = ((total_count - uncategorized) / total_count * 100) if total_count > 0 else 100

        # Check documentation
        missing_description = sum(
            1 for txn in data
            if not txn.get("description") and not txn.get("merchant_name")
        )
        documentation_score = ((total_count - missing_description) / total_count * 100) if total_count > 0 else 100

        # Calculate overall score
        overall_score = (
            receipt_score * 0.4 +
            categorization_score * 0.3 +
            documentation_score * 0.3
        )

        # Determine status
        if overall_score >= 90:
            overall_status = "compliant"
        elif overall_score >= 70:
            overall_status = "warning"
        else:
            overall_status = "critical"

        # Build indicators
        indicators = [
            ComplianceIndicator(
                id="receipt-compliance",
                name="Receipt Documentation (FAR 31.205-46)",
                status="compliant" if receipt_score >= 90 else "warning" if receipt_score >= 70 else "critical",
                score=round(receipt_score, 1),
                description=f"{receipts_missing} of {receipts_required} required receipts missing",
                last_checked=datetime.now().isoformat()
            ),
            ComplianceIndicator(
                id="categorization",
                name="Expense Categorization",
                status="compliant" if categorization_score >= 90 else "warning" if categorization_score >= 70 else "critical",
                score=round(categorization_score, 1),
                description=f"{uncategorized} transactions not categorized",
                last_checked=datetime.now().isoformat()
            ),
            ComplianceIndicator(
                id="documentation",
                name="Documentation Completeness",
                status="compliant" if documentation_score >= 90 else "warning" if documentation_score >= 70 else "critical",
                score=round(documentation_score, 1),
                description=f"{missing_description} transactions missing descriptions",
                last_checked=datetime.now().isoformat()
            )
        ]

        # Calculate compliant count
        compliant_count = sum(
            1 for txn in data
            if (abs(txn.get("amount", 0)) < 75 or txn.get("has_receipt") or txn.get("receipt_url"))
            and (txn.get("reconai_category") or txn.get("category"))
            and (txn.get("description") or txn.get("merchant_name"))
        )

        # Generate recommendations
        recommendations = []
        if receipts_missing > 0:
            recommendations.append({
                "priority": "high",
                "category": "Receipt Management",
                "title": "Upload Missing Receipts",
                "description": f"Upload receipts for {receipts_missing} transactions >= $75",
                "action": "Upload receipts to ensure FAR 31.205-46 compliance"
            })

        if uncategorized > 0:
            recommendations.append({
                "priority": "medium",
                "category": "Categorization",
                "title": "Categorize Transactions",
                "description": f"Categorize {uncategorized} uncategorized transactions",
                "action": "Assign proper expense categories for accurate reporting"
            })

        if missing_description > 0:
            recommendations.append({
                "priority": "low",
                "category": "Documentation",
                "title": "Add Descriptions",
                "description": f"Add descriptions to {missing_description} transactions",
                "action": "Add business purpose for audit trail"
            })

        return ComplianceCheckResponse(
            overall_score=round(overall_score, 1),
            overall_status=overall_status,
            indicators=indicators,
            total_transactions=total_count,
            compliant_transactions=compliant_count,
            non_compliant_transactions=total_count - compliant_count,
            recommendations=recommendations,
            report=report  # Include original report
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Compliance check failed: {str(e)}"
        )

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