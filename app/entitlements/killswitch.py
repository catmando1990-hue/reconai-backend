# app/entitlements/killswitch.py
"""
STEP 24 — Kill-Switch Mechanism for Entitlement-Gated Features

Provides a fail-closed kill-switch mechanism for:
- exports
- investor_exports
- benchmarks
- ml_governance

Kill-switches are controlled via environment variables and config.
When active, features FAIL CLOSED with structured error + request_id.

NO auto-recovery. Manual re-enablement only.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Dict, Optional, Any
from uuid import uuid4

from fastapi import HTTPException


# Kill-switch state (env-controlled, defaults to enabled/not-killed)
# Set KILLSWITCH_<FEATURE>=true to disable a feature
KILLSWITCH_CONFIG: Dict[str, str] = {
    "exports": "KILLSWITCH_EXPORTS",
    "investor_exports": "KILLSWITCH_INVESTOR_EXPORTS",
    "benchmarks": "KILLSWITCH_BENCHMARKS",
    "ml_governance": "KILLSWITCH_ML_GOVERNANCE",
}

# Feature descriptions for error messages
FEATURE_DESCRIPTIONS: Dict[str, str] = {
    "exports": "Data exports",
    "investor_exports": "Investor narrative exports",
    "benchmarks": "Activation benchmarks and cohorts",
    "ml_governance": "ML governance views",
}


def is_feature_killed(feature: str) -> bool:
    """
    Check if a feature is killed via environment variable.

    Returns True if feature is disabled (kill-switch active).
    Returns False if feature is enabled (kill-switch inactive).

    FAIL CLOSED: Unknown features default to killed.
    """
    env_var = KILLSWITCH_CONFIG.get(feature)
    if not env_var:
        # Unknown feature - fail closed
        return True

    # Check environment variable (default: not killed)
    value = os.getenv(env_var, "false").lower()
    return value in ("true", "1", "yes", "on")


def get_killswitch_status() -> Dict[str, Any]:
    """
    Get status of all kill-switches.

    Returns dictionary with status of each feature.
    """
    status = {}
    for feature, env_var in KILLSWITCH_CONFIG.items():
        is_killed = is_feature_killed(feature)
        status[feature] = {
            "env_var": env_var,
            "is_killed": is_killed,
            "status": "disabled" if is_killed else "enabled",
        }
    return status


def require_feature_enabled(
    feature: str,
    request_id: Optional[str] = None,
) -> None:
    """
    Require a feature to be enabled (not killed).

    Raises HTTPException with structured error if feature is killed.
    FAIL CLOSED with request_id.
    """
    if is_feature_killed(feature):
        # Generate request_id if not provided
        rid = request_id or str(uuid4())

        description = FEATURE_DESCRIPTIONS.get(feature, feature)

        raise HTTPException(
            status_code=503,
            detail={
                "error": "FEATURE_DISABLED",
                "code": "KILLSWITCH_ACTIVE",
                "feature": feature,
                "message": f"{description} are temporarily disabled. Please try again later.",
                "request_id": rid,
                "timestamp": datetime.utcnow().isoformat(),
                "retry_after_seconds": 300,  # Suggest retry after 5 minutes
            },
        )


def guard_feature_killswitch(
    feature: str,
    request_id: Optional[str] = None,
) -> bool:
    """
    Guard a feature with kill-switch check.

    Returns True if feature is enabled.
    Raises HTTPException if feature is killed.

    Use this in endpoint handlers before processing.
    """
    require_feature_enabled(feature, request_id)
    return True
