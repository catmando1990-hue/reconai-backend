# app/routers/reconai.py

from fastapi import APIRouter, Body
from app.reconai_core.brain import ReconAIBrain
from app.models import TransactionsRequest, TransactionsResponse

router = APIRouter(prefix="/reconai", tags=["reconai"])


@router.get("/demo", response_model=TransactionsResponse)
def demo():
    """Demo endpoint that runs sample data through ReconAIBrain."""
    brain = ReconAIBrain()

    payload = TransactionsRequest(
        source_type="structured",
        goal="business_expenses",
        transactions=[
            {
                "date": "2025-12-11",
                "amount": -89.22,
                "description": "Amazon Web Services",
                "merchant": "AWS",
                "original_category": "software",
            },
            {
                "date": "2025-12-12",
                "amount": -52.10,
                "description": "Shell Fuel",
                "merchant": "Shell",
                "original_category": "fuel",
            },
            {
                "date": "2025-12-13",
                "amount": -18.45,
                "description": "Starbucks",
                "merchant": "Starbucks",
                "original_category": "food",
            },
            {
                "date": "2025-12-14",
                "amount": 2500.00,
                "description": "Client Invoice Payment",
                "merchant": "ACME Corp",
                "original_category": "income",
            },
            {
                "date": "2025-12-15",
                "amount": -219.99,
                "description": "Office Supplies",
                "merchant": "Staples",
                "original_category": "office",
            },
            {
                "date": "2025-12-16",
                "amount": -120.00,
                "description": "Hotel Stay",
                "merchant": "Hilton",
                "original_category": "travel",
            },
            {
                "date": "2025-12-17",
                "amount": -39.99,
                "description": "Subscription",
                "merchant": "Zoom",
                "original_category": "software",
            },
        ],
    )

    return brain.analyze_transactions(payload)


@router.post("/analyze", response_model=TransactionsResponse)
def analyze(payload: TransactionsRequest = Body(...)):
    """
    Analyze raw input (csv/text/structured) via ReconAIBrain.
    """
    brain = ReconAIBrain()
    return brain.analyze_transactions(payload)
