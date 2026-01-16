# app/entitlements/__init__.py
# STEP 5 — Monetization Gates & Tier Enforcement
# STEP 24 — Kill-Switch Mechanism
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
from .killswitch import (
    is_feature_killed,
    get_killswitch_status,
    require_feature_enabled,
    guard_feature_killswitch,
)

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
    # STEP 24: Kill-switch
    "is_feature_killed",
    "get_killswitch_status",
    "require_feature_enabled",
    "guard_feature_killswitch",
]
