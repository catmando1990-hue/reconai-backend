# app/entitlements/__init__.py
# STEP 5 — Monetization Gates & Tier Enforcement
# Central entitlement definitions and guards.

from .tiers import (
    TIER_LIMITS,
    TierLimits,
    get_tier_limits,
    check_entitlement,
    require_entitlement,
    EntitlementDenied,
)
from .guards import (
    guard_export,
    guard_signals_depth,
    guard_summary_access,
)
from .audit import log_entitlement_check

__all__ = [
    "TIER_LIMITS",
    "TierLimits",
    "get_tier_limits",
    "check_entitlement",
    "require_entitlement",
    "EntitlementDenied",
    "guard_export",
    "guard_signals_depth",
    "guard_summary_access",
    "log_entitlement_check",
]
