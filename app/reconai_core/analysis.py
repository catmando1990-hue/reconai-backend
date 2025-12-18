# app/reconai_core/analysis.py

from .brain import ReconAIBrain
from ..models import TransactionsRequest, TransactionsResponse

# Shared ReconAI brain instance
brain = ReconAIBrain()


def analyze_transactions(payload: TransactionsRequest) -> TransactionsResponse:
    """
    Thin wrapper so routers can call this function.
    """
    return brain.analyze_transactions(payload)
