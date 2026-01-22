# app/intelligence/models.py
"""
Transaction Intelligence Models (Phase 1)

Pydantic models for classification results, evidence, and API contracts.

CONTRACT VERSION: 1
- All responses MUST include intelligence_version field
- All responses MUST include lifecycle (status + reason_code)
- All responses MUST include evidence metadata
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional, Any, Dict
from pydantic import BaseModel, Field

from app.guardrails import (
    INTELLIGENCE_CONTRACT_VERSION,
    create_intelligence_lifecycle,
    create_evidence_metadata,
)


# =============================================================================
# LIFECYCLE STATUS (PART 1)
# =============================================================================

IntelligenceLifecycleStatus = Literal["success", "partial", "failed", "no_data"]


class Lifecycle(BaseModel):
    """
    Lifecycle state for Intelligence responses.

    CONTRACT:
    - status: ALWAYS present (one of: success, partial, failed, no_data)
    - reason_code: ALWAYS present when status != "success", None otherwise
    """
    status: IntelligenceLifecycleStatus
    reason_code: Optional[str] = None


# =============================================================================
# EVIDENCE METADATA (PART 2)
# =============================================================================

class CoverageWindow(BaseModel):
    """Time range of data analyzed."""
    start: Optional[str] = None
    end: Optional[str] = None


class EvidenceMetadata(BaseModel):
    """
    Evidence metadata for auditability of Intelligence insights.

    CONTRACT:
    - sources: ALWAYS present (list of data sources used)
    - coverage_window: ALWAYS present (time range of data analyzed)
    - evaluated_at: ALWAYS present (ISO timestamp of evaluation)
    - confidence_score: ALWAYS present (overall confidence 0.0-1.0)
    """
    sources: List[str] = Field(default_factory=list)
    coverage_window: CoverageWindow = Field(default_factory=CoverageWindow)
    evaluated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)


# =============================================================================
# CLASSIFICATION CATEGORIES AND EVIDENCE TYPES
# =============================================================================

# Classification categories
ClassificationCategory = Literal[
    "business_expense",
    "personal_expense",
    "transfer",
    "income",
    "tax_deductible",
    "uncertain",
]

# Evidence types
EvidenceType = Literal[
    "merchant_pattern",
    "amount_pattern",
    "date_pattern",
    "description_keyword",
    "historical_classification",
    "rule_match",
    "duplicate_signal",
    "time_proximity",
]


class EvidenceItem(BaseModel):
    """Single piece of evidence supporting a classification."""

    evidence_type: EvidenceType
    value: Any
    weight: float = Field(ge=0.0, le=1.0, description="Weight contribution to confidence")
    description: str


class ClassificationResult(BaseModel):
    """Result of classifying a single transaction."""

    transaction_id: str
    category: ClassificationCategory
    confidence: float = Field(ge=0.0, le=1.0)
    explanation: str
    evidence: List[EvidenceItem]
    requires_review: bool = Field(
        description="True if confidence < 0.85 or category is 'uncertain'"
    )
    matched_rules: List[str] = Field(default_factory=list)
    classified_at: str


class DuplicateGroup(BaseModel):
    """Group of potentially duplicate transactions."""

    group_id: str
    transaction_ids: List[str]
    confidence: float = Field(ge=0.0, le=1.0)
    explanation: str
    evidence: List[EvidenceItem]
    requires_review: bool = True  # Duplicates always require review
    detected_at: str


class ClassifyRequest(BaseModel):
    """Request to classify transactions (manual-only)."""

    transaction_ids: List[str] = Field(
        min_length=1,
        max_length=100,
        description="List of transaction IDs to classify"
    )


class ClassifyResponse(BaseModel):
    """
    Response from classification endpoint.

    CONTRACT VERSION: 1
    - intelligence_version: ALWAYS present, integer
    - lifecycle: ALWAYS present (status + reason_code)
    - evidence: ALWAYS present (metadata for auditability)
    """

    # Contract version - ALWAYS present
    intelligence_version: int = INTELLIGENCE_CONTRACT_VERSION

    # Lifecycle - ALWAYS present
    lifecycle: Lifecycle = Field(
        default_factory=lambda: Lifecycle(status="success", reason_code=None)
    )

    # Evidence metadata - ALWAYS present
    evidence: EvidenceMetadata = Field(default_factory=EvidenceMetadata)

    ok: bool
    request_id: str
    classified_at: str
    classifications: List[ClassificationResult]
    duplicates: List[DuplicateGroup]
    total_processed: int
    flagged_for_review: int
    audit_event_id: str
    guardrails: Dict[str, Any] = Field(
        default_factory=lambda: {
            "confidence_threshold": 0.85,
            "writes_to_transactions": False,
            "advisory_only": False,  # Phase 1 writes to separate tables
            "manual_run_only": True,
        }
    )


class TransactionWithClassification(BaseModel):
    """Transaction joined with its classification overlay."""

    # Original transaction fields
    transaction_id: str
    tx_date: Optional[str]
    amount: float
    description: str
    merchant: Optional[str]
    original_category: Optional[str]

    # Classification overlay (from separate table)
    classification: Optional[ClassificationResult]
    duplicate_group: Optional[DuplicateGroup]
    has_classification: bool
    last_classified_at: Optional[str]


class TransactionOverlayResponse(BaseModel):
    """
    Response with transactions and their classification overlays.

    CONTRACT VERSION: 1
    - intelligence_version: ALWAYS present, integer
    - lifecycle: ALWAYS present (status + reason_code)
    - evidence: ALWAYS present (metadata for auditability)
    """

    # Contract version - ALWAYS present
    intelligence_version: int = INTELLIGENCE_CONTRACT_VERSION

    # Lifecycle - ALWAYS present
    lifecycle: Lifecycle = Field(
        default_factory=lambda: Lifecycle(status="success", reason_code=None)
    )

    # Evidence metadata - ALWAYS present
    evidence: EvidenceMetadata = Field(default_factory=EvidenceMetadata)

    ok: bool
    request_id: str
    generated_at: str
    transactions: List[TransactionWithClassification]
    total_count: int
    classified_count: int
    unclassified_count: int
    flagged_count: int
    guardrails: Dict[str, Any] = Field(
        default_factory=lambda: {
            "read_only": True,
            "source_table": "mvp_transactions",
            "overlay_tables": ["transaction_classifications", "transaction_evidence"],
        }
    )
