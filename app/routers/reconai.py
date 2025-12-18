# app/routers/reconai.py

from __future__ import annotations

from datetime import timedelta
import datetime as dt
from typing import Optional, Any, Dict, List

from fastapi import APIRouter, HTTPException, Query, Body

from plaid.exceptions import ApiException
from plaid.model.transactions_get_request import TransactionsGetRequest
from plaid.model.transactions_get_request_options import TransactionsGetRequestOptions

from app import stores
from app.models import Transaction, TransactionsRequest, TransactionsResponse
from app.plaid_client import get_plaid_client
from app.reconai_core.analysis import analyze_transactions as core_analyze_transactions

router = APIRouter(prefix="/reconai", tags=["reconai"])


def _parse_date(value: Any) -> Optional[dt.date]:
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str) and value:
        try:
            return dt.date.fromisoformat(value)
        except Exception:
            return None
    return None


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _plaid_tx_to_recon_tx(plaid_tx: Dict[str, Any]) -> Transaction:
    """
    Plaid transaction dict -> ReconAI Transaction

    Conventions:
    - ReconAI expects outflow negative (amount < 0)
    - Plaid /transactions/get typically returns outflows as positive amounts
    """
    name = (plaid_tx.get("name") or "").strip()
    merchant_name = (plaid_tx.get("merchant_name") or "").strip()
    merchant = merchant_name or name or None

    amount = _safe_float(plaid_tx.get("amount"), 0.0)

    # Dates
    date = _parse_date(plaid_tx.get("date")) or _parse_date(plaid_tx.get("authorized_date"))

    # Categories
    original_category = None
    cat = plaid_tx.get("category")
    if isinstance(cat, list) and cat:
        original_category = " > ".join(str(x) for x in cat if x)

    # Heuristic: credit card payments / transfers
    upper_name = name.upper()
    if "CREDIT CARD" in upper_name and "PAYMENT" in upper_name:
        original_category = "transfer:credit_card_payment"

    # Convert amount convention:
    # - If Plaid gives +25 (debit/outflow), ReconAI stores -25
    # - If Plaid gives -25 (credit/inflow/refund), ReconAI stores +25
    if amount > 0:
        recon_amount = -abs(amount)
    else:
        recon_amount = abs(amount)

    return Transaction(
        date=date,
        amount=recon_amount,
        description=name or (merchant or ""),
        merchant=merchant,
        original_category=original_category,
    )


@router.get("/analyze-from-plaid", response_model=TransactionsResponse)
def analyze_from_plaid(
    user_id: str = Query(..., description="User ID used to fetch Plaid access token"),
    start: Optional[dt.date] = Query(None, description="YYYY-MM-DD (defaults to 2 years ago)"),
    end: Optional[dt.date] = Query(None, description="YYYY-MM-DD (defaults to today)"),
    page_size: int = Query(500, ge=1, le=500, description="Plaid page size (max 500)"),
    max_pages: int = Query(20, ge=1, le=200, description="Safety cap to prevent infinite loops"),
):
    """
    Fetch ALL transactions from Plaid (paginated), convert to ReconAI Transaction models,
    then run ReconAI analysis.
    """
    access_token = stores.get_user_access_token(user_id)
    if not access_token:
        raise HTTPException(status_code=404, detail="No access_token stored for this user")

    if end is None:
        end = dt.date.today()
    if start is None:
        start = end - timedelta(days=730)

    client = get_plaid_client()

    try:
        offset = 0
        pages = 0
        all_plaid: List[Dict[str, Any]] = []

        while True:
            pages += 1
            if pages > max_pages:
                break

            options = TransactionsGetRequestOptions(count=page_size, offset=offset)
            req = TransactionsGetRequest(
                access_token=access_token,
                start_date=start,
                end_date=end,
                options=options,
            )
            resp = client.transactions_get(req)

            # Prefer to_dict() when available
            try:
                data = resp.to_dict()
                batch = data.get("transactions", []) or []
                total = int(data.get("total_transactions") or 0)
            except AttributeError:
                batch = getattr(resp, "transactions", []) or []
                total = 0

            # Normalize batch items to dicts
            norm_batch: List[Dict[str, Any]] = []
            for tx in batch:
                if isinstance(tx, dict):
                    norm_batch.append(tx)
                else:
                    try:
                        norm_batch.append(tx.to_dict())
                    except Exception:
                        norm_batch.append(getattr(tx, "__dict__", {}))

            all_plaid.extend(norm_batch)

            got = len(norm_batch)
            if got == 0:
                break

            offset += got

            if total and offset >= total:
                break

            if got < page_size:
                break

        recon_transactions = [_plaid_tx_to_recon_tx(tx) for tx in all_plaid]

        payload = TransactionsRequest(
            source_type="structured",
            goal="business_expenses",
            transactions=recon_transactions,
        )

        result = core_analyze_transactions(payload)

        result.summary_notes.append(
            f"Pulled {len(recon_transactions)} transactions from Plaid using pagination "
            f"(page_size={page_size}, pages={min(pages, max_pages)})."
        )
        return result

    except ApiException as e:
        raise HTTPException(status_code=500, detail=f"Plaid API error: {e.body}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Python error: {str(e)}")


@router.get("/demo", response_model=TransactionsResponse)
def demo():
    """
    Frontend-safe demo endpoint.
    Returns a stable TransactionsResponse without Plaid.
    """
    sample = [
        Transaction(
            date=dt.date.today() - timedelta(days=7),
            amount=-89.22,
            description="Amazon Web Services",
            merchant="AWS",
            original_category="software > cloud",
        ),
        Transaction(
            date=dt.date.today() - timedelta(days=6),
            amount=-52.10,
            description="Shell Fuel",
            merchant="Shell",
            original_category="travel > fuel",
        ),
        Transaction(
            date=dt.date.today() - timedelta(days=5),
            amount=-18.45,
            description="Starbucks",
            merchant="Starbucks",
            original_category="food > coffee",
        ),
        Transaction(
            date=dt.date.today() - timedelta(days=4),
            amount=2500.00,
            description="Client Invoice Payment",
            merchant="ACME Corp",
            original_category="income > invoice",
        ),
        Transaction(
            date=dt.date.today() - timedelta(days=3),
            amount=-219.99,
            description="Office Supplies",
            merchant="Staples",
            original_category="office > supplies",
        ),
        Transaction(
            date=dt.date.today() - timedelta(days=2),
            amount=-120.00,
            description="Hotel Stay",
            merchant="Hilton",
            original_category="travel > lodging",
        ),
        Transaction(
            date=dt.date.today() - timedelta(days=1),
            amount=-39.99,
            description="Subscription",
            merchant="Zoom",
            original_category="software > subscription",
        ),
    ]

    payload = TransactionsRequest(
        source_type="structured",
        goal="business_expenses",
        transactions=sample,
    )

    result = core_analyze_transactions(payload)
    result.summary_notes.append("Demo mode: sample data (no Plaid required).")
    return result


@router.post("/analyze", response_model=TransactionsResponse)
def analyze_unified(
    user_id: Optional[str] = Query(
        None,
        description="If provided, ReconAI will pull transactions from Plaid for this user_id and ignore the request body.",
    ),
    payload: Optional[TransactionsRequest] = Body(
        None,
        description="If user_id is not provided, submit a TransactionsRequest body (structured / csv / text).",
    ),
):
    """
    Unified analysis entry point for frontend use.

    - If user_id is provided → runs Plaid pipeline
    - Otherwise → runs core analysis on provided payload
    """
    # Path A: Plaid-backed analysis
    if user_id:
        return analyze_from_plaid(user_id=user_id)

    # Path B: Client-provided data
    if payload is None:
        raise HTTPException(
            status_code=400,
            detail="Provide either user_id (query param) or a TransactionsRequest body.",
        )

    return core_analyze_transactions(payload)
