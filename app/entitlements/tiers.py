# app/entitlements/tiers.py
# STEP 5 — Tier Definitions & Entitlement Checks
# Defines subscription tiers and their feature limits.
# NO auto-upgrades, NO dark patterns — audit-safe denials only.

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from fastapi import HTTPException, Request


@dataclass(frozen=True)
class TierLimits:
    """Immutable tier configuration."""
    name: str
    exports_enabled: bool
    export_limit_per_day: int  # 0 = disabled
    signals_depth: int  # Max signals to return (prioritized)
    summary_enabled: bool
    intelligence_enabled: bool
    max_transactions_per_month: int


# Tier definitions — deterministic, no external calls
TIER_LIMITS: Dict[str, TierLimits] = {
    "free": TierLimits(
        name="Free",
        exports_enabled=False,
        export_limit_per_day=0,
        signals_depth=10,
        summary_enabled=True,
        intelligence_enabled=True,
        max_transactions_per_month=100,
    ),
    "starter": TierLimits(
        name="Starter",
        exports_enabled=True,
        export_limit_per_day=5,
        signals_depth=50,
        summary_enabled=True,
        intelligence_enabled=True,
        max_transactions_per_month=500,
    ),
    "pro": TierLimits(
        name="Pro",
        exports_enabled=True,
        export_limit_per_day=50,
        signals_depth=200,
        summary_enabled=True,
        intelligence_enabled=True,
        max_transactions_per_month=5000,
    ),
    "enterprise": TierLimits(
        name="Enterprise",
        exports_enabled=True,
        export_limit_per_day=1000,
        signals_depth=1000,
        summary_enabled=True,
        intelligence_enabled=True,
        max_transactions_per_month=100000,
    ),
}


def get_tier_limits(tier: str) -> TierLimits:
    """Get limits for a tier. Defaults to 'free' for unknown tiers."""
    return TIER_LIMITS.get(tier.lower(), TIER_LIMITS["free"])


class EntitlementDenied(Exception):
    """Raised when entitlement check fails."""
    def __init__(
        self,
        feature: str,
        tier: str,
        message: str,
        upgrade_to: Optional[str] = None,
    ):
        self.feature = feature
        self.tier = tier
        self.message = message
        self.upgrade_to = upgrade_to
        super().__init__(message)


def check_entitlement(
    tier: str,
    feature: str,
    *,
    request: Optional[Request] = None,
) -> tuple[bool, Optional[str]]:
    """
    Check if a tier has access to a feature.
    Returns (allowed, upgrade_suggestion).

    NO side effects — pure check only.
    """
    limits = get_tier_limits(tier)

    if feature == "exports":
        if not limits.exports_enabled:
            return (False, "starter")
        return (True, None)

    elif feature == "signals_depth":
        # Always allowed, but depth is limited by tier
        return (True, None)

    elif feature == "summary":
        if not limits.summary_enabled:
            return (False, "starter")
        return (True, None)

    elif feature == "intelligence":
        if not limits.intelligence_enabled:
            return (False, "starter")
        return (True, None)

    # Unknown features are denied by default
    return (False, None)


def require_entitlement(
    tier: str,
    feature: str,
    *,
    request: Optional[Request] = None,
) -> TierLimits:
    """
    Require an entitlement or raise HTTPException with structured error.
    Includes request_id in error response if available.

    Returns tier limits if allowed.
    """
    allowed, upgrade_to = check_entitlement(tier, feature, request=request)

    if not allowed:
        # Get request_id from request state if available
        request_id = None
        if request:
            request_id = getattr(request.state, "request_id", None)

        error_detail = {
            "error": "ENTITLEMENT_DENIED",
            "feature": feature,
            "current_tier": tier,
            "message": f"Your {tier} plan does not include {feature}. Please upgrade to access this feature.",
        }

        if upgrade_to:
            error_detail["upgrade_to"] = upgrade_to
            error_detail["upgrade_url"] = "/settings/billing"

        if request_id:
            error_detail["request_id"] = request_id

        raise HTTPException(
            status_code=403,
            detail=error_detail,
        )

    return get_tier_limits(tier)
