from fastapi import APIRouter

from app.models import Transaction, TransactionsResponse

router = APIRouter(prefix="/reconai", tags=["reconai"])


@router.get("/demo", response_model=TransactionsResponse)
def demo():
    demo_rows = [
        Transaction(date="2025-12-11", merchant="AWS", description="Amazon Web Services", amount=-89.22, original_category="software"),
        Transaction(date="2025-12-12", merchant="Shell", description="Shell Fuel", amount=-52.10, original_category="fuel"),
        Transaction(date="2025-12-13", merchant="Starbucks", description="Starbucks", amount=-18.45, original_category="food"),
        Transaction(date="2025-12-14", merchant="ACME Corp", description="Client Invoice Payment", amount=2500.00, original_category="income"),
        Transaction(date="2025-12-15", merchant="Staples", description="Office Supplies", amount=-219.99, original_category="office"),
        Transaction(date="2025-12-16", merchant="Hilton", description="Hotel Stay", amount=-120.00, original_category="travel"),
        Transaction(date="2025-12-17", merchant="Zoom", description="Subscription", amount=-39.99, original_category="software"),
    ]

    # Minimal “already analyzed” response matching your frontend expectation
    # You can later swap this to call your real brain.
    return TransactionsResponse(
        schema_version="1.1.0",
        total_transactions=len(demo_rows),
        total_outflow=round(sum(x.amount for x in demo_rows if x.amount < 0), 2),
        total_inflow=round(sum(x.amount for x in demo_rows if x.amount > 0), 2),
        net=round(sum(x.amount for x in demo_rows), 2),
        business_expenses=demo_rows,   # keeping it simple for now
        personal_expenses=[],
        transfers=[],
        uncertain=[],
        summary_notes=["Demo endpoint: static sample data."],
    )
