# app/guardrails/stripe_hardening.py
"""
STEP 8: Stripe Production Hardening

Enforces fail-closed behavior in production:
- STRIPE_SECRET_KEY must be configured
- STRIPE_WEBHOOK_SECRET must be configured

Called at app startup to prevent boot without required secrets.
"""

import os


def enforce_stripe_prod():
    """
    Enforce Stripe secrets in production.

    Raises RuntimeError if production environment lacks required secrets.
    This prevents the app from starting in an insecure state.
    """
    # Check multiple common env var names for production detection
    env = os.getenv("ENVIRONMENT") or os.getenv("ENV") or os.getenv("NODE_ENV")

    if env == "production":
        missing = []

        if not os.getenv("STRIPE_SECRET_KEY"):
            missing.append("STRIPE_SECRET_KEY")

        if not os.getenv("STRIPE_WEBHOOK_SECRET"):
            missing.append("STRIPE_WEBHOOK_SECRET")

        if missing:
            raise RuntimeError(
                f"Stripe secrets missing in production: {', '.join(missing)}. "
                "Cannot start application without required billing configuration."
            )
