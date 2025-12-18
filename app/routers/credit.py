# app/routers/credit.py

from fastapi import APIRouter

from ..models import TransactionsRequest, CreditAnalysisResponse
from ..reconai_core.analysis import brain

router = APIRouter()


@router.post("/credit/analysis", response_model=CreditAnalysisResponse)
def credit_analysis(payload: TransactionsRequest) -> CreditAnalysisResponse:
    """
    Credit/coaching-focused analysis endpoint.
    Uses ReconAIBrain.analyze_credit().
    """
    return brain.analyze_credit(payload)
