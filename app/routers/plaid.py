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
# EXPENSE TYPE MAPPING (Category -> Business/Personal/School/Other)
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
    "Fuel": "Business",  # Can be business or personal, defaulting to business
    "Vehicle Maintenance": "Business",  # Can be business or personal, defaulting to business

    # PERSONAL expenses (not deductible)
    "Meals & Entertainment": "Personal",  # Default to personal unless business meal
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
    "Interest/Fees": "Business",  # Usually business-related

    # INVESTMENT
    "Investment": "Other",  # Could be business or personal depending on context

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
    # Schedule C Line Items (Business Income/Expenses)
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
        "notes": "SaaS subscriptions are fully deductible; software licenses may be depreciated"
    },
    "Fuel": {
        "schedule_c_line": "9",
        "line_name": "Car and Truck Expenses",
        "deduction_rate": 1.00,  # If using actual expense method
        "documentation_required": ["Receipt", "Odometer readings", "Business purpose"],
        "limits": "Must choose actual expense OR standard mileage (not both)",
        "notes": "Alternative: Use standard mileage rate ($0.67/mile for 2024)"
    },
    "Vehicle Maintenance": {
        "schedule_c_line": "9",
        "line_name": "Car and Truck Expenses",
        "deduction_rate": 1.00,  # Prorated by business use %
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
        "notes": "Unless used in a business setting (e.g., home office)"
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
    # Defense Contract Audit Agency (DCAA) requirements for government contractors

    "documentation_requirements": {
        "timely_recording": {
            "description": "Expenses must be recorded within 3-5 business days",
            "validation": "Check transaction date vs. recording date",
            "severity": "critical",
            "regulation": "FAR 31.201-2(d)"
        },
        "receipt_threshold": {
            "description": "Receipts required for expenses ≥ $75",
            "threshold": 75.00,
            "validation": "Flag transactions ≥$75 without receipt",
            "severity": "critical",
            "regulation": "FAR 31.205-46(a)"
        },
        "business_purpose": {
            "description": "All expenses must document business purpose",
            "validation": "Check for description field completion",
            "severity": "critical",
            "regulation": "FAR 31.201-2"
        },
        "supporting_documentation": {
            "description": "Maintain original receipts, invoices, contracts",
            "validation": "Verify document attachment/reference",
            "severity": "critical",
            "regulation": "FAR 52.216-7(d)"
        }
    },

    "allowable_costs": {
        # Fully allowable costs
        "Travel - Airfare": {"allowable": True, "notes": "Coach/economy required unless unavailable"},
        "Travel - Lodging": {"allowable": True, "notes": "Must not exceed GSA per-diem rates or actual costs"},
        "Travel - Ground Transportation": {"allowable": True, "notes": "Reasonable transportation costs"},
        "Office Supplies": {"allowable": True, "notes": "Ordinary and necessary supplies"},
        "Software & Subscriptions": {"allowable": True, "notes": "Must be allocable to contract"},
        "Professional Services": {"allowable": True, "notes": "Must be at reasonable rates"},
        "Utilities": {"allowable": True, "notes": "Allocable portion only"},
        "Insurance": {"allowable": True, "notes": "Required by contract or law"},

        # Partially allowable (with restrictions)
        "Meals & Entertainment": {
            "allowable": "partial",
            "deduction_rate": 0.50,
            "notes": "Meals 50% allowable; Entertainment unallowable per FAR 31.205-14"
        },
        "Fuel": {
            "allowable": True,
            "notes": "Business portion only; mileage log required"
        },

        # Unallowable costs (FAR 31.205)
        "Entertainment": {
            "allowable": False,
            "notes": "Unallowable per FAR 31.205-14 (entertainment, amusement, diversion)"
        },
        "Alcoholic Beverages": {
            "allowable": False,
            "notes": "Unallowable per FAR 31.205-51"
        },
        "Fines & Penalties": {
            "allowable": False,
            "notes": "Unallowable per FAR 31.205-15"
        },
        "Lobbying": {
            "allowable": False,
            "notes": "Unallowable per FAR 31.205-22"
        },
        "Contributions & Donations": {
            "allowable": False,
            "notes": "Unallowable per FAR 31.205-8"
        },
    },

    "timekeeping_labor": {
        "description": "Time must be recorded daily (not weekly or monthly)",
        "requirements": [
            "Sign timesheet daily or weekly (max)",
            "Record actual hours worked",
            "Identify contract/project charged",
            "Supervisor approval required",
            "No pre-signing or post-dating"
        ],
        "regulation": "FAR 31.201-2(d), DCAA audit manual"
    },

    "travel_restrictions": {
        "airfare": {
            "requirement": "Coach/economy class",
            "exception": "Business/first class only if documented medical need or unavailability",
            "regulation": "FAR 31.205-46(a)(2)"
        },
        "lodging": {
            "requirement": "GSA per-diem rate or actual cost (whichever is less)",
            "validation": "Compare to GSA rates by location",
            "regulation": "FAR 31.205-46(a)(1)"
        },
        "rental_cars": {
            "requirement": "Compact/mid-size unless business necessity",
            "unallowable": "Luxury vehicles, sports cars",
            "regulation": "FAR 31.205-46(a)(3)"
        },
        "meals": {
            "requirement": "GSA M&IE rate or actual (50% deductible for tax)",
            "unallowable": "Lavish or extravagant meals",
            "regulation": "FAR 31.205-46(a)"
        }
    },

    "documentation_retention": {
        "description": "Records must be retained for specified periods",
        "retention_periods": {
            "contracts_under_$10k": "3 years after final payment",
            "contracts_$10k_to_$150k": "3 years after final payment",
            "contracts_over_$150k": "4 years after final payment (or longer if litigation)",
            "indirect_cost_records": "Until all audits completed + 3 years"
        },
        "regulation": "FAR 4.705, FAR 52.215-2(f)"
    },

    "indirect_cost_allocation": {
        "description": "Indirect costs must be allocated using consistent, equitable methods",
        "requirements": [
            "Maintain accounting system consistent with GAAP",
            "Use consistent allocation bases",
            "Segregate direct vs. indirect costs",
            "Document allocation methodology",
            "Update annually"
        ],
        "regulation": "FAR 31.203, CAS 418"
    }
}


def validate_dcaa_compliance(transaction: dict) -> dict:
    """
    Validate transaction against DCAA compliance rules.

    Args:
        transaction: Dict with keys: merchant, amount, date, category, description, has_receipt

    Returns:
        Dict with compliance status and any violations
    """
    violations = []
    warnings = []

    category = transaction.get("category", "Uncategorized")
    amount = transaction.get("amount", 0)
    has_receipt = transaction.get("has_receipt", False)
    description = transaction.get("description", "")

    # Check 1: Receipt requirement (≥$75)
    receipt_threshold = DCAA_COMPLIANCE_RULES["documentation_requirements"]["receipt_threshold"]["threshold"]
    if amount >= receipt_threshold and not has_receipt:
        violations.append({
            "rule": "Receipt Required",
            "severity": "critical",
            "message": f"Receipt required for expense ≥ ${receipt_threshold:.2f}",
            "regulation": "FAR 31.205-46(a)",
            "remediation": "Obtain and attach receipt or credit card statement"
        })

    # Check 2: Business purpose documentation
    if not description or len(description.strip()) < 5:
        violations.append({
            "rule": "Business Purpose Required",
            "severity": "critical",
            "message": "Transaction missing business purpose documentation",
            "regulation": "FAR 31.201-2",
            "remediation": "Add detailed business purpose description"
        })

    # Check 3: Allowable cost verification
    allowable_info = DCAA_COMPLIANCE_RULES["allowable_costs"].get(category, {"allowable": True})

    if allowable_info.get("allowable") == False:
        violations.append({
            "rule": "Unallowable Cost",
            "severity": "critical",
            "message": f"{category} is unallowable under DCAA rules",
            "regulation": allowable_info.get("notes", "FAR 31.205"),
            "remediation": "Remove from government contract billing; charge to IR&D or personal"
        })
    elif allowable_info.get("allowable") == "partial":
        warnings.append({
            "rule": "Partially Allowable Cost",
            "severity": "warning",
            "message": f"{category}: {allowable_info.get('notes', 'Restrictions apply')}",
            "regulation": "FAR 31.205",
            "remediation": f"Apply {allowable_info.get('deduction_rate', 1.0):.0%} allowable rate"
        })

    # Check 4: Travel class restrictions (for airfare)
    if category == "Travel - Airfare" and amount > 500:
        warnings.append({
            "rule": "Airfare Class Verification",
            "severity": "warning",
            "message": "Verify coach/economy class used (business/first class requires justification)",
            "regulation": "FAR 31.205-46(a)(2)",
            "remediation": "Document if business class was unavailable or medically necessary"
        })

    # Calculate compliance score
    compliance_score = 100
    compliance_score -= len(violations) * 25  # Critical violations
    compliance_score -= len(warnings) * 5     # Warnings
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
    """
    Get tax deduction information for a category.

    Args:
        category: Transaction category

    Returns:
        Dict with deduction rules and documentation requirements
    """
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
    
    # School/Education
    "tuition": ("Education", "School tuition"),
    "university": ("Education", "University expense"),
    "college": ("Education", "College expense"),
    "bookstore": ("Education", "Textbooks/supplies"),
    "chegg": ("Education", "Educational service"),
    "coursera": ("Education", "Online learning"),
    "udemy": ("Education", "Online learning"),
    "pearson": ("Education", "Educational materials"),
    "mcgraw-hill": ("Education", "Educational materials"),

    # Fuel & Auto
    "shell": ("Fuel", "Gas station"),
    "chevron": ("Fuel", "Gas station"),
    "exxon": ("Fuel", "Gas station"),
    "mobil": ("Fuel", "Gas station"),
    "bp": ("Fuel", "Gas station"),
    "valero": ("Fuel", "Gas station"),
    "arco": ("Fuel", "Gas station"),
    "texaco": ("Fuel", "Gas station"),
    "sunoco": ("Fuel", "Gas station"),
    "speedway": ("Fuel", "Gas station"),
    "wawa": ("Fuel", "Gas station/convenience"),
    "7-eleven": ("Fuel", "Gas station/convenience"),
    "autozone": ("Vehicle Maintenance", "Auto parts"),
    "o'reilly": ("Vehicle Maintenance", "Auto parts"),
    "pep boys": ("Vehicle Maintenance", "Auto parts/service"),
    "jiffy lube": ("Vehicle Maintenance", "Oil change/service"),

    # Groceries & Retail
    "walmart": ("Groceries", "Grocery/retail store"),
    "target": ("Groceries", "Grocery/retail store"),
    "costco": ("Groceries", "Wholesale club"),
    "sam's club": ("Groceries", "Wholesale club"),
    "kroger": ("Groceries", "Grocery store"),
    "safeway": ("Groceries", "Grocery store"),
    "albertsons": ("Groceries", "Grocery store"),
    "publix": ("Groceries", "Grocery store"),
    "whole foods": ("Groceries", "Grocery store"),
    "trader joe": ("Groceries", "Grocery store"),
    "aldi": ("Groceries", "Grocery store"),
    "wegmans": ("Groceries", "Grocery store"),
    "heb": ("Groceries", "Grocery store"),

    # Restaurants & Dining (expanded)
    "panera": ("Meals & Entertainment", "Restaurant"),
    "olive garden": ("Meals & Entertainment", "Restaurant"),
    "red lobster": ("Meals & Entertainment", "Restaurant"),
    "chili's": ("Meals & Entertainment", "Restaurant"),
    "applebee's": ("Meals & Entertainment", "Restaurant"),
    "outback": ("Meals & Entertainment", "Restaurant"),
    "cheesecake factory": ("Meals & Entertainment", "Restaurant"),
    "buffalo wild": ("Meals & Entertainment", "Restaurant"),
    "subway": ("Meals & Entertainment", "Fast food restaurant"),
    "taco bell": ("Meals & Entertainment", "Fast food restaurant"),
    "wendy's": ("Meals & Entertainment", "Fast food restaurant"),
    "burger king": ("Meals & Entertainment", "Fast food restaurant"),
    "arby's": ("Meals & Entertainment", "Fast food restaurant"),
    "five guys": ("Meals & Entertainment", "Fast food restaurant"),
    "shake shack": ("Meals & Entertainment", "Fast food restaurant"),
    "in-n-out": ("Meals & Entertainment", "Fast food restaurant"),
    "pizza hut": ("Meals & Entertainment", "Restaurant"),
    "domino's": ("Meals & Entertainment", "Restaurant"),
    "papa john": ("Meals & Entertainment", "Restaurant"),

    # Software & SaaS (expanded)
    "notion": ("Software & Subscriptions", "Productivity software"),
    "asana": ("Software & Subscriptions", "Project management"),
    "trello": ("Software & Subscriptions", "Project management"),
    "monday.com": ("Software & Subscriptions", "Project management"),
    "jira": ("Software & Subscriptions", "Project management"),
    "confluence": ("Software & Subscriptions", "Team collaboration"),
    "figma": ("Software & Subscriptions", "Design software"),
    "canva": ("Software & Subscriptions", "Design software"),
    "mailchimp": ("Software & Subscriptions", "Email marketing"),
    "hubspot": ("Software & Subscriptions", "CRM/Marketing"),
    "salesforce": ("Software & Subscriptions", "CRM"),
    "shopify": ("Software & Subscriptions", "E-commerce platform"),
    "squarespace": ("Software & Subscriptions", "Website builder"),
    "wix": ("Software & Subscriptions", "Website builder"),
    "godaddy": ("Software & Subscriptions", "Domain/hosting"),
    "namecheap": ("Software & Subscriptions", "Domain/hosting"),
    "cloudflare": ("Software & Subscriptions", "Cloud services"),
    "digitalocean": ("Software & Subscriptions", "Cloud hosting"),
    "linode": ("Software & Subscriptions", "Cloud hosting"),
    "netlify": ("Software & Subscriptions", "Cloud hosting"),

    # Marketing & Advertising
    "google ads": ("Marketing & Advertising", "Online advertising"),
    "facebook ads": ("Marketing & Advertising", "Social media advertising"),
    "meta ads": ("Marketing & Advertising", "Social media advertising"),
    "linkedin ads": ("Marketing & Advertising", "Social media advertising"),
    "twitter ads": ("Marketing & Advertising", "Social media advertising"),
    "pinterest ads": ("Marketing & Advertising", "Social media advertising"),
    "tiktok ads": ("Marketing & Advertising", "Social media advertising"),

    # Shipping & Logistics
    "fedex": ("Shipping", "Shipping service"),
    "ups": ("Shipping", "Shipping service"),
    "usps": ("Shipping", "Shipping service"),
    "dhl": ("Shipping", "Shipping service"),

    # Utilities & Services
    "comcast": ("Utilities", "Internet/cable"),
    "xfinity": ("Utilities", "Internet/cable"),
    "spectrum": ("Utilities", "Internet/cable"),
    "verizon": ("Utilities", "Phone/internet"),
    "at&t": ("Utilities", "Phone/internet"),
    "t-mobile": ("Utilities", "Phone service"),
    "sprint": ("Utilities", "Phone service"),

    # Entertainment & Streaming
    "netflix": ("Entertainment", "Streaming service"),
    "hulu": ("Entertainment", "Streaming service"),
    "disney": ("Entertainment", "Streaming service"),
    "hbo": ("Entertainment", "Streaming service"),
    "amazon prime": ("Entertainment", "Streaming/subscription"),
    "spotify": ("Entertainment", "Music streaming"),
    "apple music": ("Entertainment", "Music streaming"),
    "youtube premium": ("Entertainment", "Streaming service"),
    "paramount": ("Entertainment", "Streaming service"),
    "peacock": ("Entertainment", "Streaming service"),

    # Pharmacy & Healthcare
    "cvs": ("Healthcare", "Pharmacy"),
    "walgreens": ("Healthcare", "Pharmacy"),
    "rite aid": ("Healthcare", "Pharmacy"),
    "kaiser": ("Healthcare", "Medical services"),
    "cigna": ("Insurance", "Health insurance"),
    "blue cross": ("Insurance", "Health insurance"),
    "aetna": ("Insurance", "Health insurance"),
    "united health": ("Insurance", "Health insurance"),

    # Insurance (expanded)
    "geico": ("Insurance", "Auto insurance"),
    "progressive": ("Insurance", "Auto insurance"),
    "state farm": ("Insurance", "Insurance"),
    "allstate": ("Insurance", "Insurance"),
    "farmers insurance": ("Insurance", "Insurance"),

    # Home & Garden
    "home depot": ("Home & Garden", "Home improvement"),
    "lowe's": ("Home & Garden", "Home improvement"),
    "ace hardware": ("Home & Garden", "Hardware store"),
    "ikea": ("Home & Garden", "Furniture"),
    "wayfair": ("Home & Garden", "Furniture/decor"),

    # Professional Services (expanded)
    "upwork": ("Professional Services", "Freelance platform"),
    "fiverr": ("Professional Services", "Freelance platform"),
    "legalzoom": ("Professional Services", "Legal services"),
    "docusign": ("Software & Subscriptions", "Document signing"),
    "notary": ("Professional Services", "Notary service"),

    # Financial Services
    "paypal": ("Payment/Transfer", "Payment service"),
    "venmo": ("Payment/Transfer", "Payment service"),
    "zelle": ("Payment/Transfer", "Payment service"),
    "cash app": ("Payment/Transfer", "Payment service"),
    "coinbase": ("Investment", "Cryptocurrency exchange"),
    "robinhood": ("Investment", "Investment platform"),
    "etrade": ("Investment", "Investment platform"),
    "fidelity": ("Investment", "Investment platform"),
    "vanguard": ("Investment", "Investment platform"),
    "charles schwab": ("Investment", "Investment platform"),
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
Classify this transaction into the most appropriate category AND determine the expense type.

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
- Education
- Groceries
- Shopping
- Entertainment
- Uncategorized

Expense types:
- Business (tax deductible business expenses)
- Personal (personal/non-deductible expenses)
- School (education-related expenses)
- Transfer (moving money between accounts)
- Income (money received)
- Other (unclear/mixed purpose)

Respond with ONLY valid JSON (no markdown, no code blocks):
{{"category": "...", "expense_type": "Business", "confidence": 85, "reasoning": "Brief explanation"}}

Rules:
- confidence: 70-99 based on certainty
- Default meals to Personal unless clearly a business meal
- Transportation during work hours = Business
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
        
    except json.JSONDecodeError as e:
        return ("Uncategorized", "Other", 60, "AI response parse error")
    except Exception as e:
        return ("Uncategorized", "Other", 50, f"AI error: {str(e)[:40]}")


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
# RECONAI CLASSIFICATION ENDPOINT (Hybrid: Rules + AI + Expense Type)
# =============================================================================

class ClassifyRequest(BaseModel):
    transactions: list[dict]

async def classify_transactions(request: ClassifyRequest):
    """
    Hybrid classification: Deterministic rules first, Claude AI fallback.
    Now includes:
    - expense_type (Business/Personal/School/Transfer/Income/Other)
    - tax_info (deduction rules, Schedule C line, documentation requirements)
    - dcaa_compliance (validation for government contractors)
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