# app/govcon/models.py
"""
GovCon / DCAA Compliance Models (Phase 2)

Pydantic models for DCAA-compliant transaction classification,
evidence chains, and export payloads.

CONTRACT VERSION: 1
- All responses MUST include govcon_version field
- All responses MUST include lifecycle (status + reason_code)
- All responses MUST include evidence metadata
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional, Any, Dict
from pydantic import BaseModel, Field

from app.govcon.contract import GOVCON_CONTRACT_VERSION


# Cost pool types per FAR 31.201
CostPoolType = Literal[
    "direct_labor",
    "direct_material",
    "direct_odc",  # Other Direct Costs
    "indirect_overhead",
    "indirect_ga",  # General & Administrative
    "indirect_fringe",
    "indirect_facilities",
    "unallocated",
]

# Allowability status per FAR 31.201
AllowabilityStatus = Literal[
    "allowable",
    "unallowable",
    "partially_allowable",
    "pending_review",
    "requires_evidence",
]

# FAR cost principle citations
FARCitation = Literal[
    "FAR_31_201_2",  # Reasonable costs
    "FAR_31_201_3",  # Allocable costs
    "FAR_31_201_4",  # Direct costs
    "FAR_31_201_5",  # Credits
    "FAR_31_201_6",  # Accounting for unallowable costs
    "FAR_31_205",    # Specific cost elements
    "FAR_31_205_1",  # Public relations
    "FAR_31_205_6",  # Compensation
    "FAR_31_205_13", # Employee morale
    "FAR_31_205_14", # Entertainment
    "FAR_31_205_22", # Lobbying
    "FAR_31_205_46", # Travel costs
    "CAS_401",       # Cost consistency
    "CAS_402",       # Allocation
    "CAS_418",       # Direct/indirect allocation
    "NONE",          # No specific citation
]


# =============================================================================
# LIFECYCLE STATUS (CONTRACT REQUIREMENT)
# =============================================================================

GovConLifecycleStatus = Literal["success", "partial", "failed", "no_data"]


class Lifecycle(BaseModel):
    """
    Lifecycle state for GovCon responses.

    CONTRACT:
    - status: ALWAYS present (one of: success, partial, failed, no_data)
    - reason_code: ALWAYS present when status != "success", None otherwise
    """
    status: GovConLifecycleStatus
    reason_code: Optional[str] = None


# =============================================================================
# EVIDENCE METADATA (CONTRACT REQUIREMENT)
# =============================================================================

class CoverageWindow(BaseModel):
    """Time range of data analyzed."""
    start: Optional[str] = None
    end: Optional[str] = None


class EvidenceMetadata(BaseModel):
    """
    Evidence metadata for auditability of GovCon responses.

    CONTRACT:
    - sources: ALWAYS present (list of data sources used)
    - coverage_window: ALWAYS present (time range of data analyzed)
    - evaluated_at: ALWAYS present (ISO timestamp of evaluation)
    - dcaa_compliant: ALWAYS present (boolean)
    """
    sources: List[str] = Field(default_factory=list)
    coverage_window: CoverageWindow = Field(default_factory=CoverageWindow)
    evaluated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    dcaa_compliant: bool = True


# =============================================================================
# EVIDENCE CHAIN MODELS
# =============================================================================

class EvidenceChainItem(BaseModel):
    """Single evidence item in the compliance chain."""

    id: str
    evidence_type: Literal[
        "far_citation",
        "policy_rule",
        "intelligence_link",
        "manual_review",
        "document_reference",
        "cost_pool_assignment",
        "allowability_determination",
    ]
    value: Any
    description: str
    created_at: str
    created_by: str
    prev_hash: Optional[str] = None  # For chain integrity
    evidence_hash: str


class GovConClassification(BaseModel):
    """GovCon compliance classification for a transaction."""

    id: str
    organization_id: str
    transaction_id: str

    # Allowability determination
    allowability: AllowabilityStatus
    far_citation: Optional[FARCitation] = None
    allowability_notes: Optional[str] = None

    # Cost pool attribution
    cost_pool: CostPoolType
    cost_pool_notes: Optional[str] = None

    # Linking to Phase 1 intelligence
    intelligence_classification_id: Optional[str] = None

    # Review status
    requires_review: bool = True
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None

    # Evidence chain
    evidence_chain: List[EvidenceChainItem] = Field(default_factory=list)

    # Audit
    classified_by: str
    classified_at: str


class GovConTransactionOverlay(BaseModel):
    """Transaction with GovCon compliance overlay (read-only join)."""

    # Original transaction fields
    transaction_id: str
    tx_date: Optional[str]
    amount: float
    description: str
    merchant: Optional[str]
    original_category: Optional[str]

    # Phase 1 intelligence classification (if exists)
    intelligence_category: Optional[str] = None
    intelligence_confidence: Optional[float] = None

    # GovCon compliance overlay
    govcon_classification: Optional[GovConClassification] = None
    has_govcon_classification: bool = False

    # Compliance flags
    dcaa_compliant: bool = False
    requires_review: bool = True
    evidence_complete: bool = False


class GovConTransactionsResponse(BaseModel):
    """
    Response with transactions and GovCon compliance overlays.

    CONTRACT VERSION: 1
    - govcon_version: ALWAYS present, integer
    - lifecycle: ALWAYS present (status + reason_code)
    - evidence: ALWAYS present (metadata for auditability)
    """

    # Contract version - ALWAYS present
    govcon_version: int = GOVCON_CONTRACT_VERSION

    # Lifecycle - ALWAYS present
    lifecycle: Lifecycle = Field(
        default_factory=lambda: Lifecycle(status="success", reason_code=None)
    )

    # Evidence metadata - ALWAYS present
    evidence: EvidenceMetadata = Field(default_factory=EvidenceMetadata)

    ok: bool
    request_id: str
    generated_at: str
    transactions: List[GovConTransactionOverlay]
    total_count: int
    classified_count: int
    allowable_count: int
    unallowable_count: int
    pending_review_count: int
    guardrails: Dict[str, Any] = Field(
        default_factory=lambda: {
            "read_only": True,
            "source_table": "mvp_transactions",
            "overlay_tables": ["govcon_classifications", "govcon_evidence_chain"],
            "dcaa_compliant": True,
        }
    )


class ExportPreviewItem(BaseModel):
    """Single item in export preview."""

    transaction_id: str
    tx_date: Optional[str]
    amount: float
    description: str
    cost_pool: CostPoolType
    allowability: AllowabilityStatus
    far_citation: Optional[str]
    evidence_count: int
    dcaa_compliant: bool


class ExportPreviewResponse(BaseModel):
    """
    Response from export preview (manual-only, no auto-export).

    CONTRACT VERSION: 1
    - govcon_version: ALWAYS present, integer
    - lifecycle: ALWAYS present (status + reason_code)
    - evidence: ALWAYS present (metadata for auditability)
    """

    # Contract version - ALWAYS present
    govcon_version: int = GOVCON_CONTRACT_VERSION

    # Lifecycle - ALWAYS present
    lifecycle: Lifecycle = Field(
        default_factory=lambda: Lifecycle(status="success", reason_code=None)
    )

    # Evidence metadata - ALWAYS present
    evidence: EvidenceMetadata = Field(default_factory=EvidenceMetadata)

    ok: bool
    request_id: str
    generated_at: str
    preview: List[ExportPreviewItem]
    summary: Dict[str, Any]
    export_ready: bool
    blocking_issues: List[str]
    audit_event_id: str
    guardrails: Dict[str, Any] = Field(
        default_factory=lambda: {
            "auto_export": False,
            "manual_trigger_required": True,
            "dcaa_compliant": True,
            "immutable_audit": True,
        }
    )
