# app/govcon/contract.py
"""
GovCon Contract Versioning (DCAA Compliance)

CONTRACT VERSION: 1
- govcon_version: ALWAYS present in all GovCon API responses (integer)

This module defines the canonical version constant and validation utilities
for all GovCon/DCAA compliance endpoints.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, FrozenSet, List, Literal, Optional, TypedDict


# =============================================================================
# CONTRACT VERSION (Strict versioning, no silent changes)
# =============================================================================

# Contract version - increment on breaking changes to GovCon API
GOVCON_CONTRACT_VERSION = 1


# =============================================================================
# LIFECYCLE MODEL
# =============================================================================

# Valid lifecycle statuses - fail-closed validation
GovConLifecycleStatus = Literal["success", "partial", "failed", "no_data"]
VALID_GOVCON_LIFECYCLE_STATUSES: FrozenSet[str] = frozenset(["success", "partial", "failed", "no_data"])


class GovConLifecycle(TypedDict):
    """
    Lifecycle state for GovCon responses.

    CONTRACT:
    - status: ALWAYS present (one of: success, partial, failed, no_data)
    - reason_code: ALWAYS present when status != "success", None otherwise
    """
    status: GovConLifecycleStatus
    reason_code: Optional[str]


def create_govcon_lifecycle(
    status: str,
    reason_code: Optional[str] = None,
) -> GovConLifecycle:
    """
    Factory for creating validated GovConLifecycle.
    Fail-closed: rejects invalid status values.

    Args:
        status: Must be one of: success, partial, failed, no_data
        reason_code: Required when status != "success"

    Raises:
        ValueError: If status is invalid or reason_code missing when required
    """
    if status not in VALID_GOVCON_LIFECYCLE_STATUSES:
        raise ValueError(
            f"Invalid GovCon lifecycle status: {status}. "
            f"Must be one of: {sorted(VALID_GOVCON_LIFECYCLE_STATUSES)}"
        )

    # Enforce reason_code requirement
    if status != "success" and not reason_code:
        raise ValueError(
            f"reason_code is required when status is '{status}'"
        )

    # Clear reason_code for success status
    if status == "success":
        reason_code = None

    return {
        "status": status,  # type: ignore
        "reason_code": reason_code,
    }


# =============================================================================
# EVIDENCE METADATA
# =============================================================================

class GovConEvidenceMetadata(TypedDict):
    """
    Evidence metadata for auditability of GovCon responses.

    CONTRACT:
    - sources: ALWAYS present (list of data sources used)
    - coverage_window: ALWAYS present (time range of data analyzed)
    - evaluated_at: ALWAYS present (ISO timestamp of evaluation)
    - dcaa_compliant: ALWAYS present (boolean indicating DCAA compliance)
    """
    sources: List[str]
    coverage_window: Dict[str, Optional[str]]  # {"start": ISO, "end": ISO}
    evaluated_at: str  # ISO timestamp
    dcaa_compliant: bool


def create_govcon_evidence(
    sources: List[str],
    coverage_start: Optional[str] = None,
    coverage_end: Optional[str] = None,
    evaluated_at: Optional[str] = None,
    dcaa_compliant: bool = True,
) -> GovConEvidenceMetadata:
    """
    Factory for creating validated GovConEvidenceMetadata.

    Args:
        sources: List of data sources (e.g., ["govcon_classifications", "evidence_chain"])
        coverage_start: ISO timestamp for start of data window
        coverage_end: ISO timestamp for end of data window
        evaluated_at: ISO timestamp of evaluation (defaults to now)
        dcaa_compliant: Whether the response is DCAA compliant

    Returns:
        Validated GovConEvidenceMetadata
    """
    return {
        "sources": sources or [],
        "coverage_window": {
            "start": coverage_start,
            "end": coverage_end,
        },
        "evaluated_at": evaluated_at or datetime.utcnow().isoformat(),
        "dcaa_compliant": dcaa_compliant,
    }


# =============================================================================
# RESPONSE ENVELOPE
# =============================================================================

class GovConResponse(TypedDict):
    """
    Standard GovCon response envelope.

    CONTRACT VERSION: 1
    - govcon_version: ALWAYS present, integer
    - lifecycle: ALWAYS present (status + reason_code)
    - evidence: ALWAYS present (metadata for auditability)
    """
    govcon_version: int  # ALWAYS present - contract version
    lifecycle: GovConLifecycle  # ALWAYS present
    evidence: GovConEvidenceMetadata  # ALWAYS present
    ok: bool


def wrap_govcon_response(
    ok: bool = True,
    sources: Optional[List[str]] = None,
    coverage_start: Optional[str] = None,
    coverage_end: Optional[str] = None,
    lifecycle_status: str = "success",
    lifecycle_reason: Optional[str] = None,
    dcaa_compliant: bool = True,
    **extra_fields,
) -> Dict[str, Any]:
    """
    Wrap a GovCon response in the standard contract envelope.

    CONTRACT VERSION: 1
    - govcon_version: ALWAYS present in response
    - lifecycle: ALWAYS present in response
    - evidence: ALWAYS present in response

    Args:
        ok: Whether the operation succeeded
        sources: List of data sources used
        coverage_start: ISO timestamp for start of data window
        coverage_end: ISO timestamp for end of data window
        lifecycle_status: Lifecycle status (success, partial, failed, no_data)
        lifecycle_reason: Reason code (required if status != success)
        dcaa_compliant: Whether response is DCAA compliant
        **extra_fields: Additional fields to include in response

    Returns:
        Complete response dict with contract version and metadata
    """
    now = datetime.utcnow().isoformat()

    lifecycle = create_govcon_lifecycle(lifecycle_status, lifecycle_reason)
    evidence = create_govcon_evidence(
        sources=sources or ["govcon_api"],
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        evaluated_at=now,
        dcaa_compliant=dcaa_compliant,
    )

    response = {
        "govcon_version": GOVCON_CONTRACT_VERSION,  # ALWAYS present
        "lifecycle": lifecycle,  # ALWAYS present
        "evidence": evidence,  # ALWAYS present
        "ok": ok,
    }

    # Add any extra fields
    response.update(extra_fields)

    return response
