# app/routers/accounting.py

from fastapi import APIRouter

from ..models import TransactionsRequest, AccountingSummaryResponse
from ..reconai_core.analysis import brain

router = APIRouter()


@router.post("/accounting/summary", response_model=AccountingSummaryResponse)
def accounting_summary(payload: TransactionsRequest) -> AccountingSummaryResponse:
    """
    Accounting-focused summary endpoint.
    Uses ReconAIBrain.analyze_accounting().
    """
    return brain.analyze_accounting(payload)
