# app/routers/tax.py

from fastapi import APIRouter

from ..models import TransactionsRequest, TaxAnalysisResponse
from ..reconai_core.analysis import brain

router = APIRouter()


@router.post("/tax/analysis", response_model=TaxAnalysisResponse)
def tax_analysis(payload: TransactionsRequest) -> TaxAnalysisResponse:
    """
    Tax-focused analysis endpoint (heuristic for now).
    Uses ReconAIBrain.analyze_tax().
    """
    return brain.analyze_tax(payload)
