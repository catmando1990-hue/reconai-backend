# app/routers/plaid.py
from datetime import timedelta
import datetime as dt

from fastapi import APIRouter, HTTPException

from plaid.exceptions import ApiException
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.products import Products
from plaid.model.country_code import CountryCode
from plaid.model.accounts_get_request import AccountsGetRequest
from plaid.model.transactions_get_request import TransactionsGetRequest
from plaid.model.transactions_get_request_options import TransactionsGetRequestOptions
from plaid.model.sandbox_public_token_create_request import SandboxPublicTokenCreateRequest

from ..models import LinkTokenRequest, PublicTokenExchangeRequest
from ..plaid_client import get_plaid_client
from .. import stores

router = APIRouter()


@router.post("/link-token")
def create_link_token(payload: LinkTokenRequest):
    client = get_plaid_client()
    request = LinkTokenCreateRequest(
        user=LinkTokenCreateRequestUser(client_user_id=payload.user_id),
        client_name="ReconAI",
        products=[Products("transactions")],
        country_codes=[CountryCode("US")],
        language="en",
    )

    try:
        response = client.link_token_create(request)
        try:
            return response.to_dict()
        except AttributeError:
            return {"link_token": response.link_token, "expiration": response.expiration}
    except ApiException as e:
        raise HTTPException(status_code=500, detail=f"Plaid API error: {e.body}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Python error: {str(e)}")


@router.post("/exchange-public-token")
def exchange_public_token(payload: PublicTokenExchangeRequest):
    client = get_plaid_client()

    try:
        request = ItemPublicTokenExchangeRequest(public_token=payload.public_token)
        response = client.item_public_token_exchange(request)

        access_token = response.access_token
        item_id = response.item_id

        # ✅ Persist to DB (survives reload/restart)
        stores.save_user_token(payload.user_id, access_token, item_id)

        return {"access_token": access_token, "item_id": item_id}
    except ApiException as e:
        raise HTTPException(status_code=500, detail=f"Plaid API error: {e.body}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Python error: {str(e)}")


@router.post("/sandbox-public-token")
def create_sandbox_public_token():
    client = get_plaid_client()

    request = SandboxPublicTokenCreateRequest(
        institution_id="ins_109508",
        initial_products=[Products("transactions")]
    )

    try:
        response = client.sandbox_public_token_create(request)
        try:
            return response.to_dict()
        except AttributeError:
            return {"public_token": response.public_token, "request_id": getattr(response, "request_id", None)}
    except ApiException as e:
        raise HTTPException(status_code=500, detail=f"Plaid API error: {e.body}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Python error: {str(e)}")


@router.get("/accounts")
def get_accounts(user_id: str):
    access_token = stores.get_user_access_token(user_id)
    if not access_token:
        raise HTTPException(status_code=404, detail="No access_token stored for this user")

    client = get_plaid_client()
    try:
        request = AccountsGetRequest(access_token=access_token)
        response = client.accounts_get(request)
        try:
            return response.to_dict()
        except AttributeError:
            return {"accounts": [a.__dict__ for a in response.accounts]}
    except ApiException as e:
        raise HTTPException(status_code=500, detail=f"Plaid API error: {e.body}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Python error: {str(e)}")


@router.get("/transactions")
def get_plaid_transactions(
    user_id: str,
    start: dt.date | None = None,
    end: dt.date | None = None,
):
    access_token = stores.get_user_access_token(user_id)
    if not access_token:
        raise HTTPException(status_code=404, detail="No access_token stored for this user")

    if end is None:
        end = dt.date.today()
    if start is None:
        start = end - timedelta(days=730)

    client = get_plaid_client()
    try:
        options = TransactionsGetRequestOptions(count=500, offset=0)
        request = TransactionsGetRequest(
            access_token=access_token,
            start_date=start,
            end_date=end,
            options=options,
        )
        response = client.transactions_get(request)
        try:
            return response.to_dict()
        except AttributeError:
            return {
                "accounts": [a.__dict__ for a in response.accounts],
                "transactions": [t.__dict__ for t in response.transactions],
            }
    except ApiException as e:
        raise HTTPException(status_code=500, detail=f"Plaid API error: {e.body}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Python error: {str(e)}")
    
@router.post("/classify-transactions")
async def classify_transactions(request: dict):
    """Classify transactions from Plaid frontend"""
    transactions = request.get("transactions", [])
    results = []
    
    for tx in transactions:
        results.append({
            "category": "Business Expense",
            "confidence": 85,
            "reasoning": f"Classified {tx.get('merchant', 'transaction')}"
        })
    
    return results