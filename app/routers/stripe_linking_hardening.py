# app/routers/stripe_linking_hardening.py
"""
ReconAI Billing — Stripe Customer/Subscription Linking Hardening

Validation utilities for Stripe customer and subscription linkage.
Used throughout billing APIs to ensure valid mappings before operations.

Requirements:
- Validate customer_id and subscription_id are non-empty
- Validate format matches Stripe ID patterns
- Reject invalid or mismatched linkages
"""

from __future__ import annotations

import re
from typing import Optional


# Stripe ID patterns
STRIPE_CUSTOMER_PATTERN = re.compile(r"^cus_[a-zA-Z0-9]{14,}$")
STRIPE_SUBSCRIPTION_PATTERN = re.compile(r"^sub_[a-zA-Z0-9]{14,}$")


def validate_customer_subscription_link(
    customer_id: Optional[str],
    subscription_id: Optional[str],
    require_both: bool = False,
) -> bool:
    """
    Validate Stripe customer/subscription linkage.

    Args:
        customer_id: Stripe customer ID (cus_xxx)
        subscription_id: Stripe subscription ID (sub_xxx)
        require_both: If True, both must be present and valid

    Returns:
        True if linkage is valid

    Raises:
        ValueError if linkage is invalid
    """
    # If require_both, both must be present
    if require_both:
        if not customer_id or not subscription_id:
            raise ValueError("Invalid Stripe linkage: both customer_id and subscription_id required")

    # Validate customer_id format if present
    if customer_id:
        if not isinstance(customer_id, str):
            raise ValueError("Invalid Stripe linkage: customer_id must be a string")
        if not STRIPE_CUSTOMER_PATTERN.match(customer_id):
            raise ValueError(f"Invalid Stripe linkage: customer_id format invalid ({customer_id[:10]}...)")

    # Validate subscription_id format if present
    if subscription_id:
        if not isinstance(subscription_id, str):
            raise ValueError("Invalid Stripe linkage: subscription_id must be a string")
        if not STRIPE_SUBSCRIPTION_PATTERN.match(subscription_id):
            raise ValueError(f"Invalid Stripe linkage: subscription_id format invalid ({subscription_id[:10]}...)")

    return True


def validate_customer_id(customer_id: Optional[str]) -> bool:
    """
    Validate Stripe customer ID format.

    Args:
        customer_id: Stripe customer ID (cus_xxx)

    Returns:
        True if valid

    Raises:
        ValueError if invalid
    """
    if not customer_id:
        raise ValueError("Invalid Stripe customer_id: empty or None")

    if not isinstance(customer_id, str):
        raise ValueError("Invalid Stripe customer_id: must be a string")

    if not STRIPE_CUSTOMER_PATTERN.match(customer_id):
        raise ValueError(f"Invalid Stripe customer_id format: {customer_id[:10]}...")

    return True


def validate_subscription_id(subscription_id: Optional[str]) -> bool:
    """
    Validate Stripe subscription ID format.

    Args:
        subscription_id: Stripe subscription ID (sub_xxx)

    Returns:
        True if valid

    Raises:
        ValueError if invalid
    """
    if not subscription_id:
        raise ValueError("Invalid Stripe subscription_id: empty or None")

    if not isinstance(subscription_id, str):
        raise ValueError("Invalid Stripe subscription_id: must be a string")

    if not STRIPE_SUBSCRIPTION_PATTERN.match(subscription_id):
        raise ValueError(f"Invalid Stripe subscription_id format: {subscription_id[:10]}...")

    return True
