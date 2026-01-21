# app/guardrails/plaid_oauth_hardening.py
"""
Plaid OAuth Production Hardening

Enforces fail-closed behavior in production:
- PLAID_CLIENT_ID must be configured
- PLAID_SECRET must be configured
- PLAID_REDIRECT_URI must be configured (required for OAuth)

Called at app startup to prevent boot without required Plaid configuration.

============================================================================
FROZEN AS OF 2024-01-20 (Phase 4 System Hardening)
============================================================================

DO NOT MODIFY THIS FILE WITHOUT FOLLOWING THE CHANGE PROCEDURE IN:
    app/plaid/FROZEN.md

Any changes require: RFC + Security Review + Migration Plan
============================================================================
"""

import os


def enforce_plaid_oauth_prod():
    """
    Enforce Plaid OAuth secrets in production.

    Raises RuntimeError if production environment lacks required secrets.
    This prevents the app from starting in an insecure state.

    Required env vars for production:
    - PLAID_CLIENT_ID: Plaid API client ID
    - PLAID_SECRET: Plaid API secret key
    - PLAID_REDIRECT_URI: OAuth redirect URI (e.g., https://app.reconai.io/plaid/oauth)
    """
    # Check multiple common env var names for production detection
    env = os.getenv("ENVIRONMENT") or os.getenv("ENV") or os.getenv("NODE_ENV")

    if env == "production":
        missing = []

        if not os.getenv("PLAID_CLIENT_ID"):
            missing.append("PLAID_CLIENT_ID")

        if not os.getenv("PLAID_SECRET"):
            missing.append("PLAID_SECRET")

        if not os.getenv("PLAID_REDIRECT_URI"):
            missing.append("PLAID_REDIRECT_URI")

        if missing:
            raise RuntimeError(
                f"Plaid OAuth secrets missing in production: {', '.join(missing)}. "
                "Cannot start application without required Plaid configuration. "
                "PLAID_REDIRECT_URI is required for OAuth bank linking flows."
            )


def warn_plaid_redirect_uri():
    """
    Warn if PLAID_REDIRECT_URI is not set in non-production environments.

    This is a soft warning - the app will still start, but OAuth flows
    may not work correctly for institutions requiring redirect.
    """
    env = os.getenv("ENVIRONMENT") or os.getenv("ENV") or os.getenv("NODE_ENV")

    if env != "production" and not os.getenv("PLAID_REDIRECT_URI"):
        print(
            "WARNING: PLAID_REDIRECT_URI not configured. "
            "OAuth flows for some institutions may fail. "
            "Set PLAID_REDIRECT_URI for full bank linking support."
        )
