# app/intelligence/rules.py
"""
Deterministic Classification Rules (Rules-First Engine)

This module implements the rules-first approach to transaction classification.
Rules are evaluated in priority order; first matching rule wins.

CANONICAL LAWS:
- Deterministic: same input always produces same output
- Explainable: every classification has traceable evidence
- Auditable: rule matches are logged
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple, Dict, Any

from app.intelligence.models import (
    ClassificationCategory,
    EvidenceItem,
    EvidenceType,
)


@dataclass(frozen=True)
class ClassificationRule:
    """Immutable classification rule definition."""

    rule_id: str
    name: str
    description: str
    category: ClassificationCategory
    priority: int  # Lower = higher priority
    base_confidence: float  # Base confidence when rule matches

    # Match conditions (all must be True for rule to match)
    merchant_patterns: Tuple[str, ...] = ()  # Regex patterns
    description_keywords: Tuple[str, ...] = ()  # Case-insensitive keywords
    amount_min: Optional[float] = None
    amount_max: Optional[float] = None
    amount_exact: Optional[float] = None


# ============================================================================
# DETERMINISTIC RULES (Priority Order)
# ============================================================================

CLASSIFICATION_RULES: List[ClassificationRule] = [
    # Priority 10-19: High-confidence business software/SaaS
    ClassificationRule(
        rule_id="RULE_001",
        name="Adobe Subscription",
        description="Adobe software subscriptions are business software expenses",
        category="business_expense",
        priority=10,
        base_confidence=0.95,
        merchant_patterns=(r"(?i)adobe",),
    ),
    ClassificationRule(
        rule_id="RULE_002",
        name="Microsoft/Office 365",
        description="Microsoft subscriptions are business software expenses",
        category="business_expense",
        priority=10,
        base_confidence=0.95,
        merchant_patterns=(r"(?i)microsoft", r"(?i)office\s*365", r"(?i)msft"),
    ),
    ClassificationRule(
        rule_id="RULE_003",
        name="Google Workspace",
        description="Google Workspace subscriptions are business software expenses",
        category="business_expense",
        priority=10,
        base_confidence=0.95,
        merchant_patterns=(r"(?i)google\s*(workspace|cloud|gsuite)",),
    ),
    ClassificationRule(
        rule_id="RULE_004",
        name="AWS/Cloud Infrastructure",
        description="Cloud infrastructure charges are business expenses",
        category="business_expense",
        priority=10,
        base_confidence=0.95,
        merchant_patterns=(r"(?i)amazon\s*web\s*services", r"(?i)aws", r"(?i)amazonaws"),
    ),
    ClassificationRule(
        rule_id="RULE_005",
        name="Slack/Communication Tools",
        description="Business communication tools are business expenses",
        category="business_expense",
        priority=10,
        base_confidence=0.94,
        merchant_patterns=(r"(?i)slack", r"(?i)zoom\s*(video)?", r"(?i)teams"),
    ),

    # Priority 20-29: Office supplies and equipment
    ClassificationRule(
        rule_id="RULE_010",
        name="Office Supplies Retailers",
        description="Office supply stores indicate business purchases",
        category="business_expense",
        priority=20,
        base_confidence=0.88,
        merchant_patterns=(r"(?i)staples", r"(?i)office\s*depot", r"(?i)office\s*max"),
    ),

    # Priority 30-39: Professional services
    ClassificationRule(
        rule_id="RULE_020",
        name="Legal Services",
        description="Legal service payments are business expenses",
        category="business_expense",
        priority=30,
        base_confidence=0.90,
        description_keywords=("legal", "attorney", "law firm", "counsel"),
    ),
    ClassificationRule(
        rule_id="RULE_021",
        name="Accounting Services",
        description="Accounting/CPA services are business expenses",
        category="business_expense",
        priority=30,
        base_confidence=0.90,
        description_keywords=("cpa", "accounting", "bookkeeping", "tax prep"),
    ),

    # Priority 40-49: Travel and transportation
    ClassificationRule(
        rule_id="RULE_030",
        name="Airlines",
        description="Airline charges may be business travel",
        category="business_expense",
        priority=40,
        base_confidence=0.75,  # Lower confidence - could be personal
        merchant_patterns=(
            r"(?i)united\s*air",
            r"(?i)delta\s*air",
            r"(?i)american\s*air",
            r"(?i)southwest",
            r"(?i)jetblue",
        ),
    ),
    ClassificationRule(
        rule_id="RULE_031",
        name="Hotels",
        description="Hotel charges may be business travel",
        category="business_expense",
        priority=40,
        base_confidence=0.70,  # Lower confidence - could be personal
        merchant_patterns=(
            r"(?i)marriott",
            r"(?i)hilton",
            r"(?i)hyatt",
            r"(?i)hotel",
            r"(?i)inn\b",
        ),
    ),

    # Priority 50-59: Personal expense patterns
    ClassificationRule(
        rule_id="RULE_040",
        name="Grocery Stores",
        description="Grocery purchases are typically personal expenses",
        category="personal_expense",
        priority=50,
        base_confidence=0.85,
        merchant_patterns=(
            r"(?i)whole\s*foods",
            r"(?i)trader\s*joe",
            r"(?i)safeway",
            r"(?i)kroger",
            r"(?i)publix",
            r"(?i)wegmans",
        ),
    ),
    ClassificationRule(
        rule_id="RULE_041",
        name="Restaurants/Dining",
        description="Restaurant charges are typically personal unless documented",
        category="personal_expense",
        priority=50,
        base_confidence=0.70,  # Could be business meals
        description_keywords=("restaurant", "cafe", "dining", "eatery"),
    ),
    ClassificationRule(
        rule_id="RULE_042",
        name="Entertainment/Streaming",
        description="Entertainment subscriptions are personal expenses",
        category="personal_expense",
        priority=50,
        base_confidence=0.90,
        merchant_patterns=(
            r"(?i)netflix",
            r"(?i)spotify",
            r"(?i)hulu",
            r"(?i)disney\+",
            r"(?i)hbo\s*max",
            r"(?i)apple\s*music",
        ),
    ),

    # Priority 60-69: Transfer patterns
    ClassificationRule(
        rule_id="RULE_050",
        name="Bank Transfers",
        description="Inter-account transfers are not expenses",
        category="transfer",
        priority=60,
        base_confidence=0.92,
        description_keywords=("transfer", "xfer", "ach", "wire"),
    ),
    ClassificationRule(
        rule_id="RULE_051",
        name="Payment Apps",
        description="P2P payment apps may be transfers",
        category="transfer",
        priority=60,
        base_confidence=0.80,
        merchant_patterns=(r"(?i)venmo", r"(?i)zelle", r"(?i)paypal\s*transfer"),
    ),

    # Priority 70-79: Income patterns
    ClassificationRule(
        rule_id="RULE_060",
        name="Payroll Deposits",
        description="Payroll deposits are income",
        category="income",
        priority=70,
        base_confidence=0.95,
        description_keywords=("payroll", "direct deposit", "salary", "wages"),
    ),
    ClassificationRule(
        rule_id="RULE_061",
        name="Interest/Dividends",
        description="Interest and dividend payments are income",
        category="income",
        priority=70,
        base_confidence=0.92,
        description_keywords=("interest", "dividend", "yield"),
    ),

    # Priority 80-89: Tax-deductible specific
    ClassificationRule(
        rule_id="RULE_070",
        name="Charitable Donations",
        description="Charitable contributions are tax-deductible",
        category="tax_deductible",
        priority=80,
        base_confidence=0.88,
        description_keywords=("donation", "charity", "nonprofit", "501c3"),
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


def _check_amount_range(
    amount: float,
    min_val: Optional[float],
    max_val: Optional[float],
    exact_val: Optional[float],
) -> bool:
    """Check if amount matches rule constraints."""
    if exact_val is not None:
        return abs(amount - exact_val) < 0.01
    if min_val is not None and amount < min_val:
        return False
    if max_val is not None and amount > max_val:
        return False
    return True


def evaluate_rule(
    rule: ClassificationRule,
    merchant: Optional[str],
    description: Optional[str],
    amount: float,
) -> Tuple[bool, List[EvidenceItem], float]:
    """
    Evaluate a single rule against transaction data.

    Returns:
        (matched, evidence_items, confidence_adjustment)
    """
    evidence: List[EvidenceItem] = []
    confidence_boost = 0.0

    # Check merchant patterns
    if rule.merchant_patterns:
        matched_patterns = _match_patterns(merchant or "", rule.merchant_patterns)
        if matched_patterns:
            evidence.append(
                EvidenceItem(
                    evidence_type="merchant_pattern",
                    value=matched_patterns,
                    weight=0.4,
                    description=f"Merchant matched patterns: {matched_patterns}",
                )
            )
            confidence_boost += 0.05
        elif rule.merchant_patterns and not rule.description_keywords:
            # Merchant patterns required but not matched
            return False, [], 0.0

    # Check description keywords
    if rule.description_keywords:
        matched_keywords = _match_keywords(description or "", rule.description_keywords)
        if matched_keywords:
            evidence.append(
                EvidenceItem(
                    evidence_type="description_keyword",
                    value=matched_keywords,
                    weight=0.3,
                    description=f"Description matched keywords: {matched_keywords}",
                )
            )
            confidence_boost += 0.03
        elif rule.description_keywords and not rule.merchant_patterns:
            # Keywords required but not matched
            return False, [], 0.0

    # Check amount constraints
    if not _check_amount_range(amount, rule.amount_min, rule.amount_max, rule.amount_exact):
        return False, [], 0.0

    if rule.amount_exact is not None or rule.amount_min is not None or rule.amount_max is not None:
        evidence.append(
            EvidenceItem(
                evidence_type="amount_pattern",
                value=amount,
                weight=0.2,
                description=f"Amount ${amount:.2f} matches rule constraints",
            )
        )

    # Must have at least one evidence item to match
    if not evidence:
        return False, [], 0.0

    # Add rule match evidence
    evidence.append(
        EvidenceItem(
            evidence_type="rule_match",
            value=rule.rule_id,
            weight=0.1,
            description=f"Matched rule: {rule.name}",
        )
    )

    return True, evidence, confidence_boost


def classify_transaction(
    transaction_id: str,
    merchant: Optional[str],
    description: Optional[str],
    amount: float,
) -> Tuple[ClassificationCategory, float, str, List[EvidenceItem], List[str]]:
    """
    Classify a transaction using deterministic rules.

    Returns:
        (category, confidence, explanation, evidence, matched_rule_ids)
    """
    # Sort rules by priority (lower = higher priority)
    sorted_rules = sorted(CLASSIFICATION_RULES, key=lambda r: r.priority)

    for rule in sorted_rules:
        matched, evidence, confidence_boost = evaluate_rule(
            rule, merchant, description, amount
        )
        if matched:
            final_confidence = min(rule.base_confidence + confidence_boost, 1.0)
            return (
                rule.category,
                final_confidence,
                rule.description,
                evidence,
                [rule.rule_id],
            )

    # No rule matched - return uncertain
    return (
        "uncertain",
        0.5,
        "No classification rule matched this transaction",
        [
            EvidenceItem(
                evidence_type="rule_match",
                value=None,
                weight=0.0,
                description="No matching rule found",
            )
        ],
        [],
    )
