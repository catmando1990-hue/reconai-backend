# app/routers/transactions.py

from fastapi import APIRouter

from ..models import TransactionsRequest, TransactionsResponse, Transaction
from ..reconai_core.analysis import analyze_transactions as core_analyze_transactions

router = APIRouter()


@router.post("/transactions", response_model=TransactionsResponse)
def analyze(payload: TransactionsRequest) -> TransactionsResponse:
    """
    Main ReconAI transaction analysis endpoint.

    Delegates to reconai_core.analysis.analyze_transactions(), then normalizes the result
    to match the current API schema (including the required 'transfers' bucket).
    """
    result = core_analyze_transactions(payload)

    # If core already returns the new schema, just pass it through
    if isinstance(result, TransactionsResponse):
        # Ensure transfers exists (just in case core returns an older object)
        if getattr(result, "transfers", None) is None:
            result.transfers = []
        return result

    # If core returns a dict (common), normalize it here
    if isinstance(result, dict):
        # Ensure required buckets exist
        result.setdefault("business_expenses", [])
        result.setdefault("personal_expenses", [])
        result.setdefault("uncertain", [])
        result.setdefault("transfers", [])  # ✅ required by new schema
        result.setdefault("summary_notes", [])

        # Ensure schema_version exists
        result.setdefault("schema_version", "1.1.0")

        return TransactionsResponse(**result)

    # Fallback: if core returns something unexpected, force a valid empty response
    return TransactionsResponse(
        schema_version="1.1.0",
        total_transactions=0,
        total_outflow=0.0,
        total_inflow=0.0,
        net=0.0,
        business_expenses=[],
        personal_expenses=[],
        transfers=[],
        uncertain=[],
        summary_notes=["Core engine returned an unsupported response type; returned empty output."],
    )
