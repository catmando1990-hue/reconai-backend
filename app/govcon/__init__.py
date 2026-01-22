# app/govcon/__init__.py
"""
GovCon / DCAA Compliance Pipeline (Phase 2)

READ-ONLY overlay for transaction classification with:
- Allowable vs unallowable tagging (policy-driven rules per FAR 31.201)
- Cost pool attribution (direct, indirect, overhead)
- Immutable evidence chain per transaction
- Integration with Phase 1 intelligence outputs

CANONICAL LAWS ENFORCED:
- Backend is source of truth
- No polling, no background jobs
- Manual-run only (export must be explicitly triggered)
- Immutable audit logging for all operations
- NO writes to source transaction tables

CONTRACT VERSION: 1
- govcon_version: ALWAYS present in all GovCon API responses
"""

from app.govcon.engine import GovConComplianceEngine
from app.govcon.models import (
    GovConClassification,
    EvidenceChainItem,
    CostPoolType,
    AllowabilityStatus,
    GovConTransactionOverlay,
    ExportPreviewResponse,
)
from app.govcon.contract import (
    GOVCON_CONTRACT_VERSION,
    VALID_GOVCON_LIFECYCLE_STATUSES,
    GovConLifecycle,
    GovConLifecycleStatus,
    GovConEvidenceMetadata,
    GovConResponse,
    create_govcon_lifecycle,
    create_govcon_evidence,
    wrap_govcon_response,
)

__all__ = [
    # Engine
    "GovConComplianceEngine",
    # Models
    "GovConClassification",
    "EvidenceChainItem",
    "CostPoolType",
    "AllowabilityStatus",
    "GovConTransactionOverlay",
    "ExportPreviewResponse",
    # Contract versioning
    "GOVCON_CONTRACT_VERSION",
    "VALID_GOVCON_LIFECYCLE_STATUSES",
    "GovConLifecycle",
    "GovConLifecycleStatus",
    "GovConEvidenceMetadata",
    "GovConResponse",
    "create_govcon_lifecycle",
    "create_govcon_evidence",
    "wrap_govcon_response",
]
