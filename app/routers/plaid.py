# app/routers/plaid.py
from datetime import timedelta
import datetime as dt
import os
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

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

# Try to import anthropic (optional - graceful fallback if not configured)
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

router = APIRouter()


# =============================================================================
# DETERMINISTIC RULES (Fast, Free - Check First)
# =============================================================================

MERCHANT_RULES = {
    # Transportation
    "uber": ("Transportation", "Rideshare service"),
    "lyft": ("Transportation", "Rideshare service"),
    "united airlines": ("Travel - Airfare", "Airline ticket"),
    "delta": ("Travel - Airfare", "Airline ticket"),
    "american airlines": ("Travel - Airfare", "Airline ticket"),
    "southwest": ("Travel - Airfare", "Airline ticket"),
    "jetblue": ("Travel - Airfare", "Airline ticket"),
    
    # Meals & Entertainment
    "starbucks": ("Meals & Entertainment", "Coffee/cafe"),
    "mcdonald": ("Meals & Entertainment", "Fast food restaurant"),
    "kfc": ("Meals & Entertainment", "Fast food restaurant"),
    "chipotle": ("Meals & Entertainment", "Restaurant"),
    "doordash": ("Meals & Entertainment", "Food delivery"),
    "grubhub": ("Meals & Entertainment", "Food delivery"),
    "uber eats": ("Meals & Entertainment", "Food delivery"),
    "dunkin": ("Meals & Entertainment", "Coffee/cafe"),
    
    # Office & Supplies
    "office depot": ("Office Supplies", "Office supply store"),
    "staples": ("Office Supplies", "Office supply store"),
    "amazon": ("Office Supplies", "Online retailer - likely business supplies"),
    
    # Software & Tech
    "github": ("Software & Subscriptions", "Developer tools"),
    "openai": ("Software & Subscriptions", "AI services"),
    "anthropic": ("Software & Subscriptions", "AI services"),
    "google cloud": ("Software & Subscriptions", "Cloud services"),
    "aws": ("Software & Subscriptions", "Cloud services"),
    "microsoft": ("Software & Subscriptions", "Software/cloud services"),
    "adobe": ("Software & Subscriptions", "Creative software"),
    "slack": ("Software & Subscriptions", "Team communication"),
    "zoom": ("Software & Subscriptions", "Video conferencing"),
    "dropbox": ("Software & Subscriptions", "Cloud storage"),
    "heroku": ("Software & Subscriptions", "Cloud hosting"),
    "vercel": ("Software & Subscriptions", "Cloud hosting"),
    "render": ("Software & Subscriptions", "Cloud hosting"),
    
    # Professional Services
    "gusto": ("Payroll", "Payroll service"),
    "quickbooks": ("Software & Subscriptions", "Accounting software"),
    "stripe": ("Payment Processing", "Payment processor"),
    "square": ("Payment Processing", "Payment processor"),
    
    # Banking & Payments
    "credit card": ("Credit Card Payment", "Credit card payment"),
    "interest": ("Interest/Fees", "Interest payment"),
    "intrst": ("Interest/Fees", "Interest payment"),
    "ach": ("Payment/Transfer", "ACH transfer"),
    "wire": ("Payment/Transfer", "Wire transfer"),
    "deposit": ("Income / Deposit", "Deposit received"),
    
    # Fitness & Health
    "touchstone climbing": ("Health & Fitness", "Gym/fitness"),
    "gym": ("Health & Fitness", "Gym membership"),
    "fitness": ("Health & Fitness", "Fitness expense"),
    "planet fitness": ("Health & Fitness", "Gym membership"),
    
    # Travel & Lodging
    "marriott": ("Travel - Lodging", "Hotel"),
    "hilton": ("Travel - Lodging", "Hotel"),
    "hyatt": ("Travel - Lodging", "Hotel"),
    "airbnb": ("Travel - Lodging", "Short-term rental"),
    "hertz": ("Travel - Ground Transportation", "Car rental"),
    "enterprise": ("Travel - Ground Transportation", "Car rental"),
    "avis": ("Travel - Ground Transportation", "Car rental"),
}

def deterministic_classify(merchant: str, amount: float):
    """Try to classify using deterministic rules."""
    merchant_lower = merchant.lower()
    
    for keyword, (category, description) in MERCHANT_RULES.items():
        if keyword in merchant_lower:
            return (category, 95, f"Matched '{keyword}' -> {description}")
    
    return None


# =============================================================================
# CLAUDE AI CLASSIFICATION (Smart Fallback)
# =============================================================================

CLASSIFICATION_PROMPT = """You are a financial classification expert for small businesses and contractors. 
Classify this transaction into the most appropriate business expense category.

Transaction:
- Merchant: {merchant}
- Amount: ${amount:.2f}
- Date: {date}

Available categories:
- Travel - Airfare
- Travel - Lodging  
- Travel - Ground Transportation
- Transportation
- Meals & Entertainment
- Office Supplies
- Software & Subscriptions
- Professional Services
- Marketing & Advertising
- Equipment & Hardware
- Utilities & Phone
- Insurance
- Payroll
- Payment Processing
- Taxes & Licenses
- Bank Fees & Interest
- Credit Card Payment
- Payment/Transfer
- Owner Draw / Personal
- Income / Deposit
- Health & Fitness
- Uncategorized

Respond with ONLY valid JSON (no markdown, no code blocks, no explanation):
{{"category": "...", "confidence": 85, "reasoning": "Brief explanation"}}

Rules:
- confidence: 70-99 based on how certain you are
- For deposits/credits (negative amounts shown as positive), consider if it's income, refund, or transfer
- For ambiguous merchants, make your best guess but lower confidence
- Keep reasoning under 100 characters"""

def get_anthropic_client():
    """Get Anthropic client if API key is configured."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key or not ANTHROPIC_AVAILABLE:
        return None
    return anthropic.Anthropic(api_key=api_key)

async def ai_classify(merchant: str, amount: float, date: str):
    """Use Claude to classify ambiguous transactions."""
    client = get_anthropic_client()
    
    if not client:
        return ("Uncategorized", 60, "AI not configured - add ANTHROPIC_API_KEY")
    
    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=150,
            messages=[{
                "role": "user",
                "content": CLASSIFICATION_PROMPT.format(
                    merchant=merchant,
                    amount=abs(amount),
                    date=date or "Unknown"
                )
            }]
        )
        
        response_text = message.content[0].text.strip()
        result = json.loads(response_text)
        
        return (
            result.get("category", "Uncategorized"),
            result.get("confidence", 75),
            result.get("reasoning", "AI classification")
        )
        
    except json.JSONDecodeError as e:
        return ("Uncategorized", 60, f"AI response parse error")
    except Exception as e:
        return ("Uncategorized", 50, f"AI error: {str(e)[:40]}")


# =============================================================================
# PLAID ENDPOINTS
# =============================================================================

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


# =============================================================================
# RECONAI CLASSIFICATION ENDPOINT (Hybrid: Rules + AI)
# =============================================================================

class ClassifyRequest(BaseModel):
    transactions: list[dict]

async def classify_transactions(request: ClassifyRequest):
    """
    Hybrid classification: Deterministic rules first, Claude AI fallback.
    Called from main.py at /classify-transactions
    """
    results = []
    
    for tx in request.transactions:
        merchant = tx.get("merchant_name") or tx.get("name") or tx.get("merchant") or "Unknown"
        amount = tx.get("amount", 0)
        date = tx.get("date", "")
        
        # Try deterministic rules first (fast, free, 95% confidence)
        rule_result = deterministic_classify(merchant, amount)
        
        if rule_result:
            category, confidence, reasoning = rule_result
            reasoning = f"[Rule] {reasoning}"
        else:
            # Fall back to Claude AI for ambiguous transactions
            category, confidence, reasoning = await ai_classify(merchant, amount, date)
            reasoning = f"[AI] {reasoning}"
        
        results.append({
            "category": category,
            "confidence": confidence,
            "reasoning": reasoning
        })
    
    return results