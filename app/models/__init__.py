# app/models/__init__.py
# Re-export all models from the original models.py for backwards compatibility
from __future__ import annotations

import datetime
from typing import List, Optional, Literal, Dict

from pydantic import BaseModel

from .audit import AuditEvent
from .policy import PolicySnapshot, FeatureFlagKey, Role
from .enterprise_roles import has_any_role
from .evidence import EvidenceItem, EvidenceType
from .rbac import RbacSnapshot, Permission
from .retention import RetentionPolicy, RetentionScope
from .export_pack import ExportPackRequest, ExportPackResponse, ExportInclude
from .support import SupportTicket, SupportTicketCreate, SupportPriority, SupportStatus


# -----------------------------
# Core transaction models
# -----------------------------

class Transaction(BaseModel):
    # Optional unique ID so feedback can remind a specific transaction.
    id: Optional[str] = None
    date: Optional[datetime.date] = None
    amount: float
    description: str
    merchant: Optional[str] = None
    original_category: Optional[str] = None

    # Classification + explanation
    classification: Optional[Literal["business", "personal", "transfer", "uncertain"]] = None
    reason: Optional[str] = None


class TransactionsRequest(BaseModel):
    """
    Flexible input model for ReconAI.

    - source_type:
        "structured" = client sends JSON list of Transaction objects
        "csv"        = client sends raw CSV text (one transaction per line)
        "text"       = client sends semi-structured text; we try to parse lines
    - goal:
        "general_analysis"  = just stats & breakdowns
        "business_expenses" = focus on business vs personal
        "tax_prep"          = tax-oriented summary (still heuristic for now)
    """
    source_type: Literal["structured", "csv", "text"] = "structured"
    goal: Literal["general_analysis", "business_expenses", "tax_prep"] = "business_expenses"

    transactions: Optional[List[Transaction]] = None
    raw_text: Optional[str] = None


class TransactionsResponse(BaseModel):
    """
    Canonical ReconAI response schema.
    """
    schema_version: str = "1.1.0"

    total_transactions: int
    total_outflow: float
    total_inflow: float
    net: float

    business_expenses: List[Transaction]
    personal_expenses: List[Transaction]
    transfers: List[Transaction]
    uncertain: List[Transaction]

    summary_notes: List[str]


# -----------------------------
# Plaid-related models
# -----------------------------

class LinkTokenRequest(BaseModel):
    user_id: str = "test-user"
    redirect_uri: Optional[str] = None  # Required for OAuth in production


class PublicTokenExchangeRequest(BaseModel):
    user_id: str = "test-user"
    public_token: str


# -----------------------------
# Accounting / Tax / Credit models
# -----------------------------

class AccountingSummaryResponse(BaseModel):
    total_income: float
    total_expenses: float
    net: float
    by_category: Dict[str, float]
    notes: List[str]


class TaxCategorySummary(BaseModel):
    label: str
    amount: float
    note: Optional[str] = None


class TaxAnalysisResponse(BaseModel):
    estimated_business_expenses: float
    potential_deductions: List[TaxCategorySummary]
    risky_items: List[Transaction]
    notes: List[str]


class CreditFactor(BaseModel):
    name: str
    status: str
    detail: Optional[str] = None


class CreditAnalysisResponse(BaseModel):
    summary: str
    factors: List[CreditFactor]
    suggested_actions: List[str]


# -----------------------------
# Feedback models
# -----------------------------

class FeedbackRequest(BaseModel):
    tx_id: str
    correct_label: Literal["business", "personal", "transfer", "uncertain"]


class FeedbackResponse(BaseModel):
    status: str
    message: str


class MerchantFeedbackRequest(BaseModel):
    merchant: str
    correct_label: Literal["business", "personal", "transfer", "uncertain"]


__all__ = [
    "AuditEvent",
    "PolicySnapshot",
    "FeatureFlagKey",
    "Role",
    "has_any_role",
    "EvidenceItem",
    "EvidenceType",
    "RbacSnapshot",
    "Permission",
    "RetentionPolicy",
    "RetentionScope",
    "ExportPackRequest",
    "ExportPackResponse",
    "ExportInclude",
    "SupportTicket",
    "SupportTicketCreate",
    "SupportPriority",
    "SupportStatus",
    "Transaction",
    "TransactionsRequest",
    "TransactionsResponse",
    "LinkTokenRequest",
    "PublicTokenExchangeRequest",
    "AccountingSummaryResponse",
    "TaxCategorySummary",
    "TaxAnalysisResponse",
    "CreditFactor",
    "CreditAnalysisResponse",
    "FeedbackRequest",
    "FeedbackResponse",
    "MerchantFeedbackRequest",
]
