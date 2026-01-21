# app/routers/plaid.py
"""
================================================================================
DEPRECATED PLAID ROUTER — PHASE 5 REGRESSION GUARD
================================================================================

WARNING: This router is DEPRECATED and DISABLED as of Phase 5 System Hardening.

REASON FOR DEPRECATION:
- Uses non-existent stores.save_user_token() and stores.get_user_access_token()
- No authentication or org-scoping
- No token encryption
- No audit logging

USE INSTEAD:
- plaid_v2.py — Production-ready Plaid API with auth, encryption, audit logging

This file is kept for reference only. All Plaid endpoints have been moved to:
    app/routers/plaid_v2.py

Any attempt to call these endpoints will raise a clear deprecation error.

================================================================================
DO NOT RE-ENABLE THESE ENDPOINTS WITHOUT SECURITY REVIEW
================================================================================
"""

from __future__ import annotations

import json
import os
from datetime import timedelta
import datetime as dt

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

# =============================================================================
# PHASE 5: DEPRECATION GUARD — All v1 endpoints are hard-disabled
# =============================================================================

router = APIRouter()

# Keep expense/tax mapping functions for classify_transactions (still used)
# But all Plaid endpoints are DEPRECATED


def _raise_deprecated_error(endpoint_name: str):
    """
    PHASE 5 REGRESSION GUARD: Raise explicit deprecation error.
    This ensures v1 endpoints cannot be silently reactivated.
    """
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail={
            "error": "DEPRECATED_ENDPOINT",
            "message": f"Endpoint '{endpoint_name}' is DEPRECATED and permanently disabled.",
            "reason": "This v1 Plaid router has security issues and missing dependencies.",
            "action": "Use the v2 Plaid API instead: /api/plaid/* (plaid_v2.py)",
            "documentation": "See app/routers/plaid_v2.py for production-ready endpoints",
        },
    )


# =============================================================================
# DEPRECATED PLAID ENDPOINTS — All return 410 Gone
# =============================================================================


@router.post("/link-token")
def create_link_token():
    """DEPRECATED: Use POST /api/plaid/create-link-token (plaid_v2.py)"""
    _raise_deprecated_error("POST /link-token")


@router.post("/exchange-public-token")
def exchange_public_token():
    """DEPRECATED: Use POST /api/plaid/exchange-public-token (plaid_v2.py)"""
    _raise_deprecated_error("POST /exchange-public-token")


@router.post("/sandbox-public-token")
def create_sandbox_public_token():
    """DEPRECATED: Sandbox endpoint disabled in production."""
    _raise_deprecated_error("POST /sandbox-public-token")


@router.get("/accounts")
def get_accounts():
    """DEPRECATED: Use GET /api/plaid/accounts (requires auth)"""
    _raise_deprecated_error("GET /accounts")


@router.get("/transactions")
def get_plaid_transactions():
    """DEPRECATED: Use POST /api/plaid/transactions/sync (plaid_v2.py)"""
    _raise_deprecated_error("GET /transactions")


# =============================================================================
# EXPENSE TYPE MAPPING (Category -> Business/Personal/School/Other)
# These are still used by classify_transactions which is NOT deprecated
# =============================================================================

EXPENSE_TYPE_MAP = {
    # BUSINESS expenses (tax deductible for business)
    "Travel - Airfare": "Business",
    "Travel - Lodging": "Business",
    "Travel - Ground Transportation": "Business",
    "Transportation": "Business",
    "Office Supplies": "Business",
    "Software & Subscriptions": "Business",
    "Professional Services": "Business",
    "Marketing & Advertising": "Business",
    "Equipment & Hardware": "Business",
    "Utilities & Phone": "Business",
    "Utilities": "Business",
    "Insurance": "Business",
    "Payroll": "Business",
    "Payment Processing": "Business",
    "Taxes & Licenses": "Business",
    "Bank Fees & Interest": "Business",
    "Shipping": "Business",
    "Fuel": "Business",
    "Vehicle Maintenance": "Business",

    # PERSONAL expenses (not deductible)
    "Meals & Entertainment": "Personal",
    "Health & Fitness": "Personal",
    "Healthcare": "Personal",
    "Owner Draw / Personal": "Personal",
    "Groceries": "Personal",
    "Shopping": "Personal",
    "Entertainment": "Personal",
    "Home & Garden": "Personal",

    # SCHOOL expenses (education-related)
    "Education": "School",

    # TRANSFERS (neither business nor personal - just moving money)
    "Credit Card Payment": "Transfer",
    "Payment/Transfer": "Transfer",

    # INCOME
    "Income / Deposit": "Income",
    "Interest/Fees": "Business",

    # INVESTMENT
    "Investment": "Other",

    # OTHER / UNCATEGORIZED
    "Uncategorized": "Other",
}


def get_expense_type(category: str) -> str:
    """Map a category to expense type (Business/Personal/School/Transfer/Income/Other)."""
    return EXPENSE_TYPE_MAP.get(category, "Other")


# =============================================================================
# TAX CATEGORY MAPPINGS & DEDUCTION RULES
# =============================================================================

TAX_DEDUCTION_RULES = {
    "Travel - Airfare": {
        "schedule_c_line": "24a",
        "line_name": "Travel - Airfare",
        "deduction_rate": 1.00,
        "documentation_required": ["Receipt", "Business purpose", "Destination", "Dates"],
        "limits": None,
        "notes": "Fully deductible if ordinary and necessary for business"
    },
    "Travel - Lodging": {
        "schedule_c_line": "24a",
        "line_name": "Travel - Lodging",
        "deduction_rate": 1.00,
        "documentation_required": ["Hotel receipt", "Business purpose", "Duration", "Location"],
        "limits": "Per-diem rates apply (or actual costs with receipts)",
        "notes": "Cannot deduct lavish or extravagant amounts"
    },
    "Travel - Ground Transportation": {
        "schedule_c_line": "24a",
        "line_name": "Travel - Car/taxi/ride-share",
        "deduction_rate": 1.00,
        "documentation_required": ["Receipt", "Business purpose", "From/To locations"],
        "limits": None,
        "notes": "Includes taxis, Uber, Lyft, car rentals"
    },
    "Meals & Entertainment": {
        "schedule_c_line": "24b",
        "line_name": "Meals (50% deductible)",
        "deduction_rate": 0.50,
        "documentation_required": ["Receipt", "Business purpose", "Attendees", "Business relationship"],
        "limits": "Cannot be lavish or extravagant",
        "notes": "Post-TCJA: Entertainment is 0% deductible, meals are 50%"
    },
    "Office Supplies": {
        "schedule_c_line": "18",
        "line_name": "Office Expense",
        "deduction_rate": 1.00,
        "documentation_required": ["Receipt", "Items purchased"],
        "limits": None,
        "notes": "Includes paper, pens, printer ink, etc."
    },
    "Software & Subscriptions": {
        "schedule_c_line": "18",
        "line_name": "Office Expense (software subscriptions)",
        "deduction_rate": 1.00,
        "documentation_required": ["Receipt/invoice", "Subscription period", "Business use"],
        "limits": "Perpetual licenses >$2,500 may need to be capitalized",
        "notes": "SaaS subscriptions are fully deductible"
    },
    "Fuel": {
        "schedule_c_line": "9",
        "line_name": "Car and Truck Expenses",
        "deduction_rate": 1.00,
        "documentation_required": ["Receipt", "Odometer readings", "Business purpose"],
        "limits": "Must choose actual expense OR standard mileage (not both)",
        "notes": "Alternative: Use standard mileage rate"
    },
    "Vehicle Maintenance": {
        "schedule_c_line": "9",
        "line_name": "Car and Truck Expenses",
        "deduction_rate": 1.00,
        "documentation_required": ["Receipt", "Business use percentage", "Mileage log"],
        "limits": "Deduct business % only (must be >50% business use)",
        "notes": "Includes repairs, oil changes, tires, etc."
    },
    "Utilities": {
        "schedule_c_line": "25",
        "line_name": "Utilities",
        "deduction_rate": 1.00,
        "documentation_required": ["Bill/receipt", "Business use justification"],
        "limits": "Home office: deduct only business % of total",
        "notes": "Includes phone, internet, electricity for business space"
    },
    "Insurance": {
        "schedule_c_line": "15",
        "line_name": "Insurance (business)",
        "deduction_rate": 1.00,
        "documentation_required": ["Policy documents", "Premium receipts"],
        "limits": None,
        "notes": "Business liability, property, errors & omissions, etc."
    },
    "Marketing & Advertising": {
        "schedule_c_line": "8",
        "line_name": "Advertising",
        "deduction_rate": 1.00,
        "documentation_required": ["Invoice", "Campaign details", "Business benefit"],
        "limits": None,
        "notes": "Includes online ads, print, sponsorships, promotions"
    },
    "Shipping": {
        "schedule_c_line": "18",
        "line_name": "Office Expense (postage/shipping)",
        "deduction_rate": 1.00,
        "documentation_required": ["Receipt", "Business purpose"],
        "limits": None,
        "notes": "Postage, freight, delivery services"
    },
    "Professional Services": {
        "schedule_c_line": "17",
        "line_name": "Legal and Professional Services",
        "deduction_rate": 1.00,
        "documentation_required": ["Invoice", "Service description"],
        "limits": None,
        "notes": "Lawyers, accountants, consultants, contractors (1099)"
    },
    "Payment Processing": {
        "schedule_c_line": "10",
        "line_name": "Commissions and Fees",
        "deduction_rate": 1.00,
        "documentation_required": ["Statement", "Transaction fees breakdown"],
        "limits": None,
        "notes": "Stripe, PayPal, Square fees"
    },
    "Education": {
        "schedule_c_line": "27a",
        "line_name": "Other Expenses - Education",
        "deduction_rate": 1.00,
        "documentation_required": ["Receipt", "Course description", "Business relevance"],
        "limits": "Must maintain or improve skills for current business",
        "notes": "Cannot be to qualify for new trade/business"
    },
    "Home & Garden": {
        "schedule_c_line": None,
        "line_name": "Non-deductible (Personal)",
        "deduction_rate": 0.00,
        "documentation_required": None,
        "limits": "Personal expenses not deductible",
        "notes": "Unless used in a business setting"
    },
    "Groceries": {
        "schedule_c_line": None,
        "line_name": "Non-deductible (Personal)",
        "deduction_rate": 0.00,
        "documentation_required": None,
        "limits": "Personal groceries not deductible",
        "notes": "Exception: meals provided to employees may be deductible"
    },
    "Healthcare": {
        "schedule_c_line": None,
        "line_name": "Self-employed health insurance (Form 1040 Schedule 1)",
        "deduction_rate": 1.00,
        "documentation_required": ["Insurance statement", "Proof of self-employment"],
        "limits": "Limited to net profit from business",
        "notes": "Deducted on Form 1040, not Schedule C"
    },
    "Entertainment": {
        "schedule_c_line": None,
        "line_name": "Non-deductible (Post-TCJA 2017)",
        "deduction_rate": 0.00,
        "documentation_required": None,
        "limits": "Entertainment expenses eliminated by TCJA",
        "notes": "Concerts, sporting events, golf, theater = 0% deductible"
    },
}


# =============================================================================
# DCAA COMPLIANCE VALIDATION RULES
# =============================================================================

DCAA_COMPLIANCE_RULES = {
    "documentation_requirements": {
        "timely_recording": {
            "description": "Expenses must be recorded within 3-5 business days",
            "validation": "Check transaction date vs. recording date",
            "severity": "critical",
            "regulation": "FAR 31.201-2(d)"
        },
        "receipt_threshold": {
            "description": "Receipts required for expenses >= $75",
            "threshold": 75.00,
            "validation": "Flag transactions >=$75 without receipt",
            "severity": "critical",
            "regulation": "FAR 31.205-46(a)"
        },
        "business_purpose": {
            "description": "All expenses must document business purpose",
            "validation": "Check for description field completion",
            "severity": "critical",
            "regulation": "FAR 31.201-2"
        },
    },
    "allowable_costs": {
        "Travel - Airfare": {"allowable": True, "notes": "Coach/economy required"},
        "Travel - Lodging": {"allowable": True, "notes": "Must not exceed GSA per-diem"},
        "Travel - Ground Transportation": {"allowable": True, "notes": "Reasonable costs"},
        "Office Supplies": {"allowable": True, "notes": "Ordinary and necessary"},
        "Software & Subscriptions": {"allowable": True, "notes": "Must be allocable"},
        "Professional Services": {"allowable": True, "notes": "Reasonable rates"},
        "Utilities": {"allowable": True, "notes": "Allocable portion only"},
        "Insurance": {"allowable": True, "notes": "Required by contract or law"},
        "Meals & Entertainment": {
            "allowable": "partial",
            "deduction_rate": 0.50,
            "notes": "Meals 50%; Entertainment unallowable per FAR 31.205-14"
        },
        "Fuel": {"allowable": True, "notes": "Business portion only"},
        "Entertainment": {"allowable": False, "notes": "Unallowable per FAR 31.205-14"},
    },
}


def validate_dcaa_compliance(transaction: dict) -> dict:
    """Validate transaction against DCAA compliance rules."""
    violations = []
    warnings = []

    category = transaction.get("category", "Uncategorized")
    amount = transaction.get("amount", 0)
    has_receipt = transaction.get("has_receipt", False)
    description = transaction.get("description", "")

    # Check 1: Receipt requirement (>=$75)
    receipt_threshold = DCAA_COMPLIANCE_RULES["documentation_requirements"]["receipt_threshold"]["threshold"]
    if amount >= receipt_threshold and not has_receipt:
        violations.append({
            "rule": "Receipt Required",
            "severity": "critical",
            "message": f"Receipt required for expense >= ${receipt_threshold:.2f}",
            "regulation": "FAR 31.205-46(a)",
        })

    # Check 2: Business purpose documentation
    if not description or len(description.strip()) < 5:
        violations.append({
            "rule": "Business Purpose Required",
            "severity": "critical",
            "message": "Transaction missing business purpose documentation",
            "regulation": "FAR 31.201-2",
        })

    # Check 3: Allowable cost verification
    allowable_info = DCAA_COMPLIANCE_RULES["allowable_costs"].get(category, {"allowable": True})

    if allowable_info.get("allowable") is False:
        violations.append({
            "rule": "Unallowable Cost",
            "severity": "critical",
            "message": f"{category} is unallowable under DCAA rules",
            "regulation": allowable_info.get("notes", "FAR 31.205"),
        })
    elif allowable_info.get("allowable") == "partial":
        warnings.append({
            "rule": "Partially Allowable Cost",
            "severity": "warning",
            "message": f"{category}: {allowable_info.get('notes', 'Restrictions apply')}",
            "regulation": "FAR 31.205",
        })

    compliance_score = 100 - (len(violations) * 25) - (len(warnings) * 5)
    compliance_score = max(0, compliance_score)

    return {
        "compliant": len(violations) == 0,
        "compliance_score": compliance_score,
        "violations": violations,
        "warnings": warnings,
        "category_allowable": allowable_info.get("allowable", True),
        "notes": allowable_info.get("notes", "")
    }


def get_tax_deduction_info(category: str) -> dict:
    """Get tax deduction information for a category."""
    return TAX_DEDUCTION_RULES.get(category, {
        "schedule_c_line": None,
        "line_name": "Uncategorized",
        "deduction_rate": 0.00,
        "documentation_required": ["Receipt", "Business purpose"],
        "limits": "Review for deductibility",
        "notes": "Consult tax professional for proper classification"
    })


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
    "chipotle": ("Meals & Entertainment", "Restaurant"),
    "doordash": ("Meals & Entertainment", "Food delivery"),
    "grubhub": ("Meals & Entertainment", "Food delivery"),
    "uber eats": ("Meals & Entertainment", "Food delivery"),

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

    # Professional Services
    "gusto": ("Payroll", "Payroll service"),
    "quickbooks": ("Software & Subscriptions", "Accounting software"),
    "stripe": ("Payment Processing", "Payment processor"),
    "square": ("Payment Processing", "Payment processor"),

    # Banking & Payments
    "credit card": ("Credit Card Payment", "Credit card payment"),
    "interest": ("Interest/Fees", "Interest payment"),
    "deposit": ("Income / Deposit", "Deposit received"),

    # Fitness & Health
    "gym": ("Health & Fitness", "Gym membership"),
    "fitness": ("Health & Fitness", "Fitness expense"),

    # Travel & Lodging
    "marriott": ("Travel - Lodging", "Hotel"),
    "hilton": ("Travel - Lodging", "Hotel"),
    "airbnb": ("Travel - Lodging", "Short-term rental"),
    "hertz": ("Travel - Ground Transportation", "Car rental"),

    # Fuel & Auto
    "shell": ("Fuel", "Gas station"),
    "chevron": ("Fuel", "Gas station"),
    "exxon": ("Fuel", "Gas station"),

    # Groceries
    "walmart": ("Groceries", "Grocery/retail store"),
    "target": ("Groceries", "Grocery/retail store"),
    "costco": ("Groceries", "Wholesale club"),

    # Shipping
    "fedex": ("Shipping", "Shipping service"),
    "ups": ("Shipping", "Shipping service"),
    "usps": ("Shipping", "Shipping service"),

    # Utilities
    "comcast": ("Utilities", "Internet/cable"),
    "verizon": ("Utilities", "Phone/internet"),
    "at&t": ("Utilities", "Phone/internet"),

    # Entertainment
    "netflix": ("Entertainment", "Streaming service"),
    "spotify": ("Entertainment", "Music streaming"),
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

# Try to import anthropic (optional - graceful fallback if not configured)
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False


CLASSIFICATION_PROMPT = """You are a financial classification expert for small businesses.
Classify this transaction into the most appropriate category AND determine the expense type.

Transaction:
- Merchant: {merchant}
- Amount: ${amount:.2f}
- Date: {date}

Available categories:
- Travel - Airfare, Travel - Lodging, Travel - Ground Transportation
- Transportation, Meals & Entertainment, Office Supplies
- Software & Subscriptions, Professional Services, Marketing & Advertising
- Equipment & Hardware, Utilities & Phone, Insurance, Payroll
- Payment Processing, Taxes & Licenses, Bank Fees & Interest
- Credit Card Payment, Payment/Transfer, Owner Draw / Personal
- Income / Deposit, Health & Fitness, Education, Groceries
- Shopping, Entertainment, Uncategorized

Expense types: Business, Personal, School, Transfer, Income, Other

Respond with ONLY valid JSON:
{{"category": "...", "expense_type": "Business", "confidence": 85, "reasoning": "Brief explanation"}}"""


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
        return ("Uncategorized", "Other", 60, "AI not configured - add ANTHROPIC_API_KEY")

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=200,
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
            result.get("expense_type", "Other"),
            result.get("confidence", 75),
            result.get("reasoning", "AI classification")
        )

    except json.JSONDecodeError:
        return ("Uncategorized", "Other", 60, "AI response parse error")
    except Exception as e:
        return ("Uncategorized", "Other", 50, f"AI error: {str(e)[:40]}")


# =============================================================================
# CLASSIFY TRANSACTIONS ENDPOINT (NOT DEPRECATED - Still in use)
# =============================================================================

class ClassifyRequest(BaseModel):
    transactions: list[dict]


async def classify_transactions(request: ClassifyRequest):
    """
    Hybrid classification: Deterministic rules first, Claude AI fallback.
    Includes expense_type, tax_info, and dcaa_compliance.

    NOTE: This endpoint is NOT deprecated. It provides transaction
    classification which is separate from Plaid bank connectivity.
    """
    results = []

    for tx in request.transactions:
        merchant = tx.get("merchant_name") or tx.get("name") or tx.get("merchant") or "Unknown"
        amount = tx.get("amount", 0)
        date = tx.get("date", "")
        description = tx.get("description", merchant)
        has_receipt = tx.get("has_receipt", False)

        # Try deterministic rules first (fast, free, 95% confidence)
        rule_result = deterministic_classify(merchant, amount)

        if rule_result:
            category, confidence, reasoning = rule_result
            expense_type = get_expense_type(category)
            reasoning = f"[Rule] {reasoning}"
        else:
            # Fall back to Claude AI for ambiguous transactions
            category, expense_type, confidence, reasoning = await ai_classify(merchant, amount, date)
            reasoning = f"[AI] {reasoning}"

        # Get tax deduction information
        tax_info = get_tax_deduction_info(category)

        # Validate DCAA compliance (for government contractors)
        dcaa_validation = validate_dcaa_compliance({
            "merchant": merchant,
            "amount": amount,
            "date": date,
            "category": category,
            "description": description,
            "has_receipt": has_receipt
        })

        results.append({
            "category": category,
            "expense_type": expense_type,
            "confidence": confidence,
            "reasoning": reasoning,
            "tax_info": {
                "schedule_c_line": tax_info.get("schedule_c_line"),
                "line_name": tax_info.get("line_name"),
                "deduction_rate": tax_info.get("deduction_rate"),
                "deductible_amount": amount * tax_info.get("deduction_rate", 0),
                "documentation_required": tax_info.get("documentation_required"),
                "limits": tax_info.get("limits"),
                "notes": tax_info.get("notes")
            },
            "dcaa_compliance": {
                "compliant": dcaa_validation.get("compliant"),
                "compliance_score": dcaa_validation.get("compliance_score"),
                "violations": dcaa_validation.get("violations", []),
                "warnings": dcaa_validation.get("warnings", []),
                "category_allowable": dcaa_validation.get("category_allowable"),
                "notes": dcaa_validation.get("notes", "")
            }
        })

    return results
