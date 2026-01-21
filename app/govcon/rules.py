# app/govcon/rules.py
"""
GovCon Allowability & Cost Pool Rules (Policy-Driven)

Deterministic rules for DCAA compliance classification:
- Allowable vs unallowable determination per FAR 31.201
- Cost pool attribution (direct, indirect, overhead)

CANONICAL LAWS:
- Deterministic: same input always produces same output
- Explainable: every classification has traceable FAR citation
- Auditable: rule matches are logged with evidence
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from app.govcon.models import (
    CostPoolType,
    AllowabilityStatus,
    FARCitation,
    EvidenceChainItem,
)


@dataclass(frozen=True)
class AllowabilityRule:
    """Immutable allowability rule definition per FAR 31.201."""

    rule_id: str
    name: str
    description: str
    allowability: AllowabilityStatus
    far_citation: FARCitation
    priority: int  # Lower = higher priority

    # Match conditions
    merchant_patterns: Tuple[str, ...] = ()
    description_keywords: Tuple[str, ...] = ()
    category_patterns: Tuple[str, ...] = ()


@dataclass(frozen=True)
class CostPoolRule:
    """Immutable cost pool attribution rule per CAS 418."""

    rule_id: str
    name: str
    description: str
    cost_pool: CostPoolType
    priority: int

    # Match conditions
    merchant_patterns: Tuple[str, ...] = ()
    description_keywords: Tuple[str, ...] = ()
    category_patterns: Tuple[str, ...] = ()
    amount_min: Optional[float] = None
    amount_max: Optional[float] = None


# ============================================================================
# ALLOWABILITY RULES (FAR 31.201 / FAR 31.205)
# ============================================================================

ALLOWABILITY_RULES: List[AllowabilityRule] = [
    # Priority 10-19: Explicitly UNALLOWABLE per FAR 31.205
    AllowabilityRule(
        rule_id="ALLOW_001",
        name="Entertainment Costs",
        description="Entertainment, including amusement, diversion, and social activities, is unallowable per FAR 31.205-14",
        allowability="unallowable",
        far_citation="FAR_31_205_14",
        priority=10,
        description_keywords=("entertainment", "amusement", "concert", "sporting event", "tickets", "show"),
    ),
    AllowabilityRule(
        rule_id="ALLOW_002",
        name="Alcoholic Beverages",
        description="Costs of alcoholic beverages are unallowable per FAR 31.205-51",
        allowability="unallowable",
        far_citation="FAR_31_205",
        priority=10,
        description_keywords=("alcohol", "beer", "wine", "liquor", "bar tab", "cocktail"),
        merchant_patterns=(r"(?i)bar\b", r"(?i)brewery", r"(?i)winery", r"(?i)liquor"),
    ),
    AllowabilityRule(
        rule_id="ALLOW_003",
        name="Lobbying Costs",
        description="Lobbying and political activity costs are unallowable per FAR 31.205-22",
        allowability="unallowable",
        far_citation="FAR_31_205_22",
        priority=10,
        description_keywords=("lobbying", "lobbyist", "political", "campaign", "pac"),
    ),
    AllowabilityRule(
        rule_id="ALLOW_004",
        name="Fines and Penalties",
        description="Fines, penalties, and related costs are unallowable per FAR 31.205-15",
        allowability="unallowable",
        far_citation="FAR_31_205",
        priority=10,
        description_keywords=("fine", "penalty", "citation", "infraction", "violation"),
    ),
    AllowabilityRule(
        rule_id="ALLOW_005",
        name="Country Club Dues",
        description="Membership costs for country clubs and social organizations are unallowable per FAR 31.205-14",
        allowability="unallowable",
        far_citation="FAR_31_205_14",
        priority=10,
        description_keywords=("country club", "golf club", "social club", "membership dues"),
        merchant_patterns=(r"(?i)country\s*club", r"(?i)golf\s*club"),
    ),
    AllowabilityRule(
        rule_id="ALLOW_006",
        name="First Class Airfare",
        description="First class airfare is unallowable unless specifically authorized per FAR 31.205-46",
        allowability="unallowable",
        far_citation="FAR_31_205_46",
        priority=10,
        description_keywords=("first class", "business class", "premium cabin"),
    ),

    # Priority 20-29: Partially Allowable
    AllowabilityRule(
        rule_id="ALLOW_010",
        name="Executive Compensation Above Cap",
        description="Executive compensation above the statutory cap is unallowable per FAR 31.205-6",
        allowability="partially_allowable",
        far_citation="FAR_31_205_6",
        priority=20,
        description_keywords=("executive bonus", "ceo compensation", "officer salary"),
    ),
    AllowabilityRule(
        rule_id="ALLOW_011",
        name="Meals and Lodging",
        description="Meals and lodging allowable per GSA rates; excess is unallowable per FAR 31.205-46",
        allowability="partially_allowable",
        far_citation="FAR_31_205_46",
        priority=20,
        description_keywords=("meal", "lodging", "hotel", "food", "restaurant"),
        merchant_patterns=(r"(?i)marriott", r"(?i)hilton", r"(?i)hyatt", r"(?i)hotel"),
    ),

    # Priority 30-39: Allowable with documentation
    AllowabilityRule(
        rule_id="ALLOW_020",
        name="Professional Services",
        description="Professional and consultant service costs are allowable when reasonable per FAR 31.205-33",
        allowability="allowable",
        far_citation="FAR_31_205",
        priority=30,
        description_keywords=("legal", "accounting", "consulting", "cpa", "attorney", "professional service"),
    ),
    AllowabilityRule(
        rule_id="ALLOW_021",
        name="Office Supplies",
        description="Material costs including office supplies are allowable per FAR 31.205-26",
        allowability="allowable",
        far_citation="FAR_31_205",
        priority=30,
        description_keywords=("office supplies", "stationery", "printer", "paper"),
        merchant_patterns=(r"(?i)staples", r"(?i)office\s*depot", r"(?i)office\s*max"),
    ),
    AllowabilityRule(
        rule_id="ALLOW_022",
        name="Software Subscriptions",
        description="EDP costs including software are allowable when allocable per FAR 31.205-25",
        allowability="allowable",
        far_citation="FAR_31_205",
        priority=30,
        merchant_patterns=(r"(?i)adobe", r"(?i)microsoft", r"(?i)google", r"(?i)aws", r"(?i)slack", r"(?i)zoom"),
    ),
    AllowabilityRule(
        rule_id="ALLOW_023",
        name="Telecommunications",
        description="Telecommunications costs are allowable per FAR 31.205-43",
        allowability="allowable",
        far_citation="FAR_31_205",
        priority=30,
        description_keywords=("phone", "telecommunications", "internet", "wireless", "cellular"),
        merchant_patterns=(r"(?i)verizon", r"(?i)at&t", r"(?i)t-mobile", r"(?i)comcast"),
    ),
    AllowabilityRule(
        rule_id="ALLOW_024",
        name="Training Costs",
        description="Training and education costs are allowable per FAR 31.205-44",
        allowability="allowable",
        far_citation="FAR_31_205",
        priority=30,
        description_keywords=("training", "education", "seminar", "conference", "certification"),
    ),
    AllowabilityRule(
        rule_id="ALLOW_025",
        name="Insurance",
        description="Insurance costs are allowable per FAR 31.205-19",
        allowability="allowable",
        far_citation="FAR_31_205",
        priority=30,
        description_keywords=("insurance", "premium", "policy", "coverage"),
    ),
    AllowabilityRule(
        rule_id="ALLOW_026",
        name="Standard Travel",
        description="Economy travel costs are allowable when reasonable per FAR 31.205-46",
        allowability="allowable",
        far_citation="FAR_31_205_46",
        priority=30,
        description_keywords=("economy", "coach", "standard"),
        merchant_patterns=(r"(?i)united", r"(?i)delta", r"(?i)american\s*air", r"(?i)southwest"),
    ),
]


# ============================================================================
# COST POOL RULES (CAS 418)
# ============================================================================

COST_POOL_RULES: List[CostPoolRule] = [
    # Priority 10-19: Direct Labor
    CostPoolRule(
        rule_id="POOL_001",
        name="Direct Labor - Salaries",
        description="Direct labor salaries charged to contracts per CAS 418",
        cost_pool="direct_labor",
        priority=10,
        description_keywords=("salary", "wages", "payroll", "direct labor", "hourly"),
    ),
    CostPoolRule(
        rule_id="POOL_002",
        name="Direct Labor - Overtime",
        description="Overtime labor charged to contracts per CAS 418",
        cost_pool="direct_labor",
        priority=10,
        description_keywords=("overtime", "ot hours"),
    ),

    # Priority 20-29: Direct Material
    CostPoolRule(
        rule_id="POOL_010",
        name="Direct Material - Purchased",
        description="Materials purchased for specific contracts per CAS 418",
        cost_pool="direct_material",
        priority=20,
        description_keywords=("material", "raw material", "inventory", "supplies", "parts"),
    ),
    CostPoolRule(
        rule_id="POOL_011",
        name="Direct Material - Subcontracts",
        description="Subcontractor costs charged to contracts",
        cost_pool="direct_material",
        priority=20,
        description_keywords=("subcontract", "subcontractor", "sub-k"),
    ),

    # Priority 30-39: Other Direct Costs (ODC)
    CostPoolRule(
        rule_id="POOL_020",
        name="ODC - Travel",
        description="Travel costs charged directly to contracts",
        cost_pool="direct_odc",
        priority=30,
        description_keywords=("travel", "airfare", "hotel", "lodging", "per diem"),
        merchant_patterns=(r"(?i)airline", r"(?i)hotel", r"(?i)marriott", r"(?i)hilton"),
    ),
    CostPoolRule(
        rule_id="POOL_021",
        name="ODC - Equipment Rental",
        description="Equipment rental charged to contracts",
        cost_pool="direct_odc",
        priority=30,
        description_keywords=("rental", "equipment", "lease"),
    ),

    # Priority 40-49: Indirect Overhead
    CostPoolRule(
        rule_id="POOL_030",
        name="Indirect - Overhead Supplies",
        description="Indirect supplies and materials per CAS 418",
        cost_pool="indirect_overhead",
        priority=40,
        description_keywords=("office supplies", "cleaning", "maintenance"),
        merchant_patterns=(r"(?i)staples", r"(?i)office\s*depot"),
    ),
    CostPoolRule(
        rule_id="POOL_031",
        name="Indirect - IT Infrastructure",
        description="IT and software costs not charged to specific contracts",
        cost_pool="indirect_overhead",
        priority=40,
        merchant_patterns=(r"(?i)microsoft", r"(?i)adobe", r"(?i)google\s*(workspace|cloud)", r"(?i)aws"),
    ),
    CostPoolRule(
        rule_id="POOL_032",
        name="Indirect - Telecommunications",
        description="Phone and internet costs not charged to specific contracts",
        cost_pool="indirect_overhead",
        priority=40,
        merchant_patterns=(r"(?i)verizon", r"(?i)at&t", r"(?i)comcast"),
    ),

    # Priority 50-59: G&A
    CostPoolRule(
        rule_id="POOL_040",
        name="G&A - Professional Services",
        description="General management and professional services per CAS 418",
        cost_pool="indirect_ga",
        priority=50,
        description_keywords=("legal", "accounting", "consulting", "audit", "tax"),
    ),
    CostPoolRule(
        rule_id="POOL_041",
        name="G&A - Insurance",
        description="General and administrative insurance costs",
        cost_pool="indirect_ga",
        priority=50,
        description_keywords=("insurance", "liability", "coverage"),
    ),
    CostPoolRule(
        rule_id="POOL_042",
        name="G&A - Bank Fees",
        description="Banking and financial service fees",
        cost_pool="indirect_ga",
        priority=50,
        description_keywords=("bank fee", "service charge", "wire fee"),
    ),

    # Priority 60-69: Fringe Benefits
    CostPoolRule(
        rule_id="POOL_050",
        name="Fringe - Health Insurance",
        description="Employee health insurance costs",
        cost_pool="indirect_fringe",
        priority=60,
        description_keywords=("health insurance", "medical", "dental", "vision", "hsa", "fsa"),
    ),
    CostPoolRule(
        rule_id="POOL_051",
        name="Fringe - Retirement",
        description="Retirement plan contributions",
        cost_pool="indirect_fringe",
        priority=60,
        description_keywords=("401k", "retirement", "pension", "ira"),
    ),

    # Priority 70-79: Facilities
    CostPoolRule(
        rule_id="POOL_060",
        name="Facilities - Rent",
        description="Facility rental and lease costs",
        cost_pool="indirect_facilities",
        priority=70,
        description_keywords=("rent", "lease", "facility", "office space"),
    ),
    CostPoolRule(
        rule_id="POOL_061",
        name="Facilities - Utilities",
        description="Utility costs for facilities",
        cost_pool="indirect_facilities",
        priority=70,
        description_keywords=("electric", "gas", "water", "utility"),
    ),
]


def _match_patterns(text: str, patterns: Tuple[str, ...]) -> List[str]:
    """Return list of matched patterns."""
    if not text or not patterns:
        return []
    matched = []
    for pattern in patterns:
        if re.search(pattern, text):
            matched.append(pattern)
    return matched


def _match_keywords(text: str, keywords: Tuple[str, ...]) -> List[str]:
    """Return list of matched keywords (case-insensitive)."""
    if not text or not keywords:
        return []
    text_lower = text.lower()
    return [kw for kw in keywords if kw.lower() in text_lower]


def determine_allowability(
    merchant: Optional[str],
    description: Optional[str],
    category: Optional[str],
) -> Tuple[AllowabilityStatus, Optional[FARCitation], str, List[str]]:
    """
    Determine allowability status per FAR 31.201.

    Returns:
        (allowability, far_citation, explanation, matched_rule_ids)
    """
    sorted_rules = sorted(ALLOWABILITY_RULES, key=lambda r: r.priority)

    for rule in sorted_rules:
        matched = False

        # Check merchant patterns
        if rule.merchant_patterns:
            if _match_patterns(merchant or "", rule.merchant_patterns):
                matched = True

        # Check description keywords
        if rule.description_keywords:
            if _match_keywords(description or "", rule.description_keywords):
                matched = True

        # Check category patterns
        if rule.category_patterns:
            if _match_patterns(category or "", rule.category_patterns):
                matched = True

        if matched:
            return (
                rule.allowability,
                rule.far_citation,
                rule.description,
                [rule.rule_id],
            )

    # Default: requires review
    return (
        "pending_review",
        "NONE",
        "No specific FAR allowability rule matched. Manual review required.",
        [],
    )


def determine_cost_pool(
    merchant: Optional[str],
    description: Optional[str],
    category: Optional[str],
    amount: float,
) -> Tuple[CostPoolType, str, List[str]]:
    """
    Determine cost pool attribution per CAS 418.

    Returns:
        (cost_pool, explanation, matched_rule_ids)
    """
    sorted_rules = sorted(COST_POOL_RULES, key=lambda r: r.priority)

    for rule in sorted_rules:
        matched = False

        # Check amount constraints
        if rule.amount_min is not None and amount < rule.amount_min:
            continue
        if rule.amount_max is not None and amount > rule.amount_max:
            continue

        # Check merchant patterns
        if rule.merchant_patterns:
            if _match_patterns(merchant or "", rule.merchant_patterns):
                matched = True

        # Check description keywords
        if rule.description_keywords:
            if _match_keywords(description or "", rule.description_keywords):
                matched = True

        # Check category patterns
        if rule.category_patterns:
            if _match_patterns(category or "", rule.category_patterns):
                matched = True

        if matched:
            return (
                rule.cost_pool,
                rule.description,
                [rule.rule_id],
            )

    # Default: unallocated
    return (
        "unallocated",
        "No specific cost pool rule matched. Manual allocation required.",
        [],
    )
