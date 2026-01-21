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
import sys
import base64


def _log_env_probe() -> None:
    """
    TEMPORARY: Log whether ENCRYPTION_KEY is visible to the runtime.

    This is an operator verification probe for Render deployment debugging.
    REMOVE THIS FUNCTION after confirming Render env is configured correctly.

    Security: Logs presence ONLY (boolean), never the key value.
    """
    key_present = os.getenv("ENCRYPTION_KEY") is not None
    env = os.getenv("ENVIRONMENT") or os.getenv("ENV") or os.getenv("RENDER_SERVICE_NAME") or "unknown"
    render_flag = "RENDER" if os.getenv("RENDER") else "NON-RENDER"

    print(f"[STARTUP] Env probe: ENCRYPTION_KEY present = {str(key_present).lower()}, env = {env}, platform = {render_flag}")


def _abort_startup(reason: str, hint: str) -> None:
    """
    Print a clear, operator-friendly error message and abort startup.

    Output format (single line per item, no stack trace):
        ENCRYPTION_KEY validation failed: <reason>
        Hint: <hint>
        Startup aborted (fail-closed)

    Then raises RuntimeError to halt the application.
    """
    print(f"\n[FATAL] ENCRYPTION_KEY validation failed: {reason}", file=sys.stderr)
    print(f"[FATAL] Hint: {hint}", file=sys.stderr)
    print(f"[FATAL] Startup aborted (fail-closed)\n", file=sys.stderr)
    raise RuntimeError(f"ENCRYPTION_KEY validation failed: {reason}")


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
        _abort_startup(
            reason="ENCRYPTION_KEY environment variable is not set",
            hint="Generate with: python -c 'import os,base64; print(base64.b64encode(os.urandom(32)).decode())'"
        )

    # Check 2: Must be valid base64
    try:
        decoded = base64.b64decode(key, validate=True)
    except Exception:
        _abort_startup(
            reason="ENCRYPTION_KEY is not valid base64 encoding",
            hint="Generate with: python -c 'import os,base64; print(base64.b64encode(os.urandom(32)).decode())'"
        )

    # Check 3: Must be exactly 32 bytes (256-bit)
    if len(decoded) != 32:
        _abort_startup(
            reason=f"ENCRYPTION_KEY must be exactly 32 bytes (got {len(decoded)} bytes)",
            hint="Generate with: python -c 'import os,base64; print(base64.b64encode(os.urandom(32)).decode())'"
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

    # TEMPORARY: Env visibility probe for Render debugging
    # REMOVE after confirming env is configured correctly
    _log_env_probe()

    # Always validate - encryption is required in all environments
    # The validate_encryption_key() function handles all cases
    validate_encryption_key()

    # Log success (without revealing the key)
    if env == "production":
        print(">> ENCRYPTION_KEY validated (production mode, fail-closed enforced)")
    else:
        print(">> ENCRYPTION_KEY validated (development mode)")
