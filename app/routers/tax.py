# app/routers/tax.py

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import List, Optional

from ..models import TransactionsRequest, TaxAnalysisResponse
from ..reconai_core.analysis import brain

router = APIRouter(prefix="/api", tags=["Tax"])


# =========================================================================
# MODELS FOR FRONTEND COMPATIBILITY
# =========================================================================

class TaxOptimizationRequest(BaseModel):
    """Tax optimization request from frontend"""
    transactions: List[dict]
    year: Optional[int] = None
    user_type: Optional[str] = "individual"


class TaxOptimizationResponse(BaseModel):
    """Tax optimization response for frontend"""
    total_deductions: float
    potential_savings: float
    recommendations: List[dict]
    quarterly_estimates: List[dict]


# =========================================================================
# ENDPOINTS
# =========================================================================

@router.post("/tax/analysis", response_model=TaxAnalysisResponse)
def tax_analysis(payload: TransactionsRequest) -> TaxAnalysisResponse:
    """
    Tax-focused analysis endpoint (heuristic for now).
    Uses ReconAIBrain.analyze_tax().
    """
    return brain.analyze_tax(payload)


@router.post("/tax/optimize", response_model=TaxOptimizationResponse)
async def optimize_taxes(request: TaxOptimizationRequest):
    """
    Tax optimization endpoint for frontend

    Analyzes transactions and provides tax optimization recommendations
    """
    try:
        # Calculate total deductions from business expenses
        total_deductions = 0.0
        business_transactions = []

        for txn in request.transactions:
            category = txn.get("reconai_category", "")
            if category and category not in ["Personal", "Transfer", "Income"]:
                amount = abs(txn.get("amount", 0))
                total_deductions += amount
                business_transactions.append(txn)

        # Estimate tax savings (simplified - 25% effective tax rate)
        potential_savings = total_deductions * 0.25

        # Generate recommendations
        recommendations = [
            {
                "category": "Business Expenses",
                "amount": total_deductions,
                "description": "Track all business-related expenses for deductions",
                "priority": "high"
            },
            {
                "category": "Quarterly Estimates",
                "amount": potential_savings / 4,
                "description": "Make quarterly estimated tax payments to avoid penalties",
                "priority": "medium"
            }
        ]

        # Generate quarterly estimates (simplified)
        from datetime import datetime
        current_year = request.year or datetime.now().year
        quarterly_estimates = [
            {"quarter": "Q1", "due_date": f"{current_year}-04-15", "amount": potential_savings / 4},
            {"quarter": "Q2", "due_date": f"{current_year}-06-15", "amount": potential_savings / 4},
            {"quarter": "Q3", "due_date": f"{current_year}-09-15", "amount": potential_savings / 4},
            {"quarter": "Q4", "due_date": f"{current_year + 1}-01-15", "amount": potential_savings / 4},
        ]

        return TaxOptimizationResponse(
            total_deductions=round(total_deductions, 2),
            potential_savings=round(potential_savings, 2),
            recommendations=recommendations,
            quarterly_estimates=quarterly_estimates
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Tax optimization failed: {str(e)}"
        )
