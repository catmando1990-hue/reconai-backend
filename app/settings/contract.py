# app/settings/contract.py
"""
Settings Contract Versioning

CONTRACT VERSION: 1
- settings_version: ALWAYS present in all Settings API responses (integer)

This module defines the canonical version constant and validation utilities
for all settings-related endpoints (user preferences, notifications, controls).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, FrozenSet, List, Literal, Optional, TypedDict


# =============================================================================
# CONTRACT VERSION (Strict versioning, no silent changes)
# =============================================================================

# Contract version - increment on breaking changes to Settings API
SETTINGS_CONTRACT_VERSION = 1


# =============================================================================
# LIFECYCLE MODEL
# =============================================================================

# Valid lifecycle statuses - fail-closed validation
SettingsLifecycleStatus = Literal["success", "partial", "failed", "no_data"]
VALID_SETTINGS_LIFECYCLE_STATUSES: FrozenSet[str] = frozenset(
    ["success", "partial", "failed", "no_data"]
)


class SettingsLifecycle(TypedDict):
    """
    Lifecycle state for Settings responses.

    CONTRACT:
    - status: ALWAYS present (one of: success, partial, failed, no_data)
    - reason_code: ALWAYS present when status != "success", None otherwise
    """

    status: SettingsLifecycleStatus
    reason_code: Optional[str]


def create_settings_lifecycle(
    status: str,
    reason_code: Optional[str] = None,
) -> SettingsLifecycle:
    """
    Factory for creating validated SettingsLifecycle.
    Fail-closed: rejects invalid status values.

    Args:
        status: Must be one of: success, partial, failed, no_data
        reason_code: Required when status != "success"

    Raises:
        ValueError: If status is invalid or reason_code missing when required
    """
    if status not in VALID_SETTINGS_LIFECYCLE_STATUSES:
        raise ValueError(
            f"Invalid Settings lifecycle status: {status}. "
            f"Must be one of: {sorted(VALID_SETTINGS_LIFECYCLE_STATUSES)}"
        )

    # Enforce reason_code requirement
    if status != "success" and not reason_code:
        raise ValueError(f"reason_code is required when status is '{status}'")

    # Clear reason_code for success status
    if status == "success":
        reason_code = None

    return {
        "status": status,  # type: ignore
        "reason_code": reason_code,
    }


# =============================================================================
# SETTINGS METADATA
# =============================================================================


class SettingsMetadata(TypedDict):
    """
    Metadata for Settings responses.

    CONTRACT:
    - sources: ALWAYS present (list of data sources used)
    - scope: ALWAYS present (user, organization, or system)
    - last_modified_at: ALWAYS present (ISO timestamp of last modification)
    - modified_by: ALWAYS present (user ID or "system")
    """

    sources: List[str]  # Data sources used
    scope: str  # "user", "organization", or "system"
    last_modified_at: str  # ISO timestamp of last modification
    modified_by: Optional[str]  # User ID or "system"


def create_settings_metadata(
    sources: List[str],
    scope: str = "user",
    last_modified_at: Optional[str] = None,
    modified_by: Optional[str] = None,
) -> SettingsMetadata:
    """
    Factory for creating validated SettingsMetadata.

    Args:
        sources: List of data sources (e.g., ["users", "notifications"])
        scope: Settings scope - "user", "organization", or "system"
        last_modified_at: ISO timestamp of last modification (defaults to now)
        modified_by: User ID who last modified, or "system"

    Returns:
        Validated SettingsMetadata
    """
    valid_scopes = {"user", "organization", "system"}
    if scope not in valid_scopes:
        raise ValueError(
            f"Invalid settings scope: {scope}. Must be one of: {sorted(valid_scopes)}"
        )

    return {
        "sources": sources or [],
        "scope": scope,
        "last_modified_at": last_modified_at or datetime.utcnow().isoformat(),
        "modified_by": modified_by,
    }


# =============================================================================
# RESPONSE ENVELOPE
# =============================================================================


class SettingsResponse(TypedDict):
    """
    Standard Settings response envelope.

    CONTRACT VERSION: 1
    - settings_version: ALWAYS present, integer
    - lifecycle: ALWAYS present (status + reason_code)
    - metadata: ALWAYS present (sources, scope, timestamps)
    """

    settings_version: int  # ALWAYS present - contract version
    lifecycle: SettingsLifecycle  # ALWAYS present
    metadata: SettingsMetadata  # ALWAYS present
    ok: bool


def wrap_settings_response(
    ok: bool = True,
    sources: Optional[List[str]] = None,
    scope: str = "user",
    last_modified_at: Optional[str] = None,
    modified_by: Optional[str] = None,
    lifecycle_status: str = "success",
    lifecycle_reason: Optional[str] = None,
    **extra_fields,
) -> Dict[str, Any]:
    """
    Wrap a Settings response in the standard contract envelope.

    CONTRACT VERSION: 1
    - settings_version: ALWAYS present in response
    - lifecycle: ALWAYS present in response
    - metadata: ALWAYS present in response

    Args:
        ok: Whether the operation succeeded
        sources: List of data sources used
        scope: Settings scope - "user", "organization", or "system"
        last_modified_at: ISO timestamp of last modification
        modified_by: User ID who last modified
        lifecycle_status: Lifecycle status (success, partial, failed, no_data)
        lifecycle_reason: Reason code (required if status != success)
        **extra_fields: Additional fields to include in response

    Returns:
        Complete response dict with contract version and metadata
    """
    now = datetime.utcnow().isoformat()

    lifecycle = create_settings_lifecycle(lifecycle_status, lifecycle_reason)
    metadata = create_settings_metadata(
        sources=sources or ["settings_api"],
        scope=scope,
        last_modified_at=last_modified_at or now,
        modified_by=modified_by,
    )

    response = {
        "settings_version": SETTINGS_CONTRACT_VERSION,  # ALWAYS present
        "lifecycle": lifecycle,  # ALWAYS present
        "metadata": metadata,  # ALWAYS present
        "ok": ok,
    }

    # Add any extra fields
    response.update(extra_fields)

    return response
