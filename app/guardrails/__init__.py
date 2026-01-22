# app/guardrails/__init__.py

from .require_approved_run import enforce_approved_run
from .intelligence_contract import (
    INTELLIGENCE_CONTRACT_VERSION,
    CONFIDENCE_THRESHOLD,
    # Lifecycle model (PART 1)
    IntelligenceLifecycle,
    IntelligenceLifecycleStatus,
    VALID_LIFECYCLE_STATUSES,
    create_intelligence_lifecycle,
    # Evidence metadata (PART 2)
    IntelligenceEvidenceMetadata,
    create_evidence_metadata,
    # Contract enforcement
    enforce_contract,
    validate_intelligence_result,
    apply_confidence_gating,
    wrap_intelligence_response,
)
from .plaid_oauth_hardening import (
    enforce_plaid_oauth_prod,
    warn_plaid_redirect_uri,
)
from .encryption_hardening import (
    validate_encryption_key,
    enforce_encryption_key_prod,
)

__all__ = [
    "enforce_approved_run",
    "INTELLIGENCE_CONTRACT_VERSION",
    "CONFIDENCE_THRESHOLD",
    # Lifecycle model
    "IntelligenceLifecycle",
    "IntelligenceLifecycleStatus",
    "VALID_LIFECYCLE_STATUSES",
    "create_intelligence_lifecycle",
    # Evidence metadata
    "IntelligenceEvidenceMetadata",
    "create_evidence_metadata",
    # Contract enforcement
    "enforce_contract",
    "validate_intelligence_result",
    "apply_confidence_gating",
    "wrap_intelligence_response",
    "enforce_plaid_oauth_prod",
    "warn_plaid_redirect_uri",
    "validate_encryption_key",
    "enforce_encryption_key_prod",
]
