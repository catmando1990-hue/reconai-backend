# app/guardrails/encryption_hardening.py
"""
P0: ENCRYPTION_KEY Startup Validation

Enforces fail-closed behavior at application startup:
- ENCRYPTION_KEY must exist
- ENCRYPTION_KEY must be valid base64
- ENCRYPTION_KEY must decode to exactly 32 bytes (256-bit)

This prevents:
- Silent runtime failures during Plaid token exchange
- Partial persistence of secrets due to encryption failures
- Ambiguous EXCHANGE_FAILED errors that mask configuration issues

Called at app startup BEFORE any routers are initialized.
If validation fails, the server MUST NOT start.
"""

import os
import base64


def validate_encryption_key() -> None:
    """
    Validate ENCRYPTION_KEY at startup.

    Validation rules (non-negotiable):
    1. Must exist in environment
    2. Must be valid base64 (decodable with validate=True)
    3. Must decode to exactly 32 bytes (256-bit AES key)

    Raises:
        RuntimeError: If any validation fails. Server must not start.

    Note:
        - Does NOT log the key value (security)
        - Does NOT auto-generate a fallback key
        - Runs once, deterministically, at boot
    """
    key = os.getenv("ENCRYPTION_KEY")

    # Check 1: Must exist
    if not key:
        raise RuntimeError(
            "ENCRYPTION_KEY must be set. "
            "Generate with: python -c 'import os,base64; print(base64.b64encode(os.urandom(32)).decode())'"
        )

    # Check 2: Must be valid base64
    try:
        decoded = base64.b64decode(key, validate=True)
    except Exception:
        raise RuntimeError(
            "ENCRYPTION_KEY is not valid base64. "
            "Ensure the key is properly base64-encoded."
        )

    # Check 3: Must be exactly 32 bytes (256-bit)
    if len(decoded) != 32:
        raise RuntimeError(
            f"ENCRYPTION_KEY must decode to exactly 32 bytes (got {len(decoded)}). "
            "Generate a new key with: python -c 'import os,base64; print(base64.b64encode(os.urandom(32)).decode())'"
        )


def enforce_encryption_key_prod() -> None:
    """
    Enforce ENCRYPTION_KEY validation in production.

    This function is called at startup. In production, a missing or invalid
    key is a fatal error. In development, it logs a warning but still validates
    to catch issues early.

    Raises:
        RuntimeError: If ENCRYPTION_KEY is missing or invalid (always, regardless of env).
    """
    env = os.getenv("ENVIRONMENT") or os.getenv("ENV") or os.getenv("NODE_ENV")

    # Always validate - encryption is required in all environments
    # The validate_encryption_key() function handles all cases
    validate_encryption_key()

    # Log success (without revealing the key)
    if env == "production":
        print(">> ENCRYPTION_KEY validated (production mode, fail-closed enforced)")
    else:
        print(">> ENCRYPTION_KEY validated (development mode)")
