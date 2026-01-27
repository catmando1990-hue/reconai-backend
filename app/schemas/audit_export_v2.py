# app/schemas/audit_export_v2.py
"""
Pydantic Models for Audit Export v2

Explicit typing for audit safety and evidence-grade exports.
All models are immutable (frozen=True) to prevent accidental mutation.

CANONICAL LAWS:
- No mutations after creation
- All fields explicitly typed
- Validation at boundaries
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# =============================================================================
# REQUEST MODELS
# =============================================================================

class AuditExportV2Request(BaseModel):
    """Request body for generating audit export v2."""

    include_statements: bool = Field(
        default=True,
        description="Include statements section in export"
    )
    include_assets: bool = Field(
        default=True,
        description="Include assets section in export"
    )
    include_liabilities: bool = Field(
        default=True,
        description="Include liabilities section in export"
    )

    class Config:
        frozen = True


# =============================================================================
# SECTION DATA MODELS
# =============================================================================

class StatementRecord(BaseModel):
    """A single statement record from local storage."""

    statement_id: int
    source: str
    total: float
    currency: str
    created_at: str
    raw_data: Optional[Dict[str, Any]] = None

    class Config:
        frozen = True


class ReceiptRecord(BaseModel):
    """A single receipt record from local storage."""

    receipt_id: int
    source: str
    total: float
    currency: str
    created_at: str
    raw_data: Optional[Dict[str, Any]] = None

    class Config:
        frozen = True


class StatementsSection(BaseModel):
    """Statements section data for export."""

    organization_id: str
    generated_at: str
    statements: List[StatementRecord]
    statements_count: int
    receipts: List[ReceiptRecord]
    receipts_count: int
    data_source: str = "local_database"
    disclaimer: str = Field(
        default="Statement data from local storage. PDFs not included in this export."
    )

    class Config:
        frozen = True


class DerivedAccountSummary(BaseModel):
    """Account summary derived from transaction data."""

    account_id: Optional[str]
    transaction_count: int
    total_credits: float
    total_debits: float
    derived_balance: float
    last_transaction_date: Optional[str]

    class Config:
        frozen = True


class AssetSnapshotSection(BaseModel):
    """Asset snapshot section data for export."""

    snapshot_type: str = "derived_from_transactions"
    generated_at: str
    accounts: List[DerivedAccountSummary]
    accounts_count: int
    total_assets_derived: float
    disclaimer: str = Field(
        default=(
            "This snapshot is derived from stored transaction data. "
            "It does not represent a live balance or official Plaid Asset Report. "
            "For authoritative asset data, generate a Plaid Asset Report via the assets/report/create endpoint."
        )
    )
    label: str = "Derived Asset Summary (from stored transactions)"

    class Config:
        frozen = True


class LiabilitiesSection(BaseModel):
    """Liabilities section data for export."""

    snapshot_type: str = "derived_from_transactions"
    generated_at: str
    credit_cards: List[Dict[str, Any]] = Field(default_factory=list)
    student_loans: List[Dict[str, Any]] = Field(default_factory=list)
    mortgages: List[Dict[str, Any]] = Field(default_factory=list)
    other_loans: List[Dict[str, Any]] = Field(default_factory=list)
    derived_liability_accounts: List[DerivedAccountSummary]
    derived_liability_count: int
    total_liabilities_derived: float
    disclaimer: str = Field(
        default=(
            "This snapshot is derived from stored transaction data. "
            "It does not represent official Plaid Liabilities data. "
            "For authoritative liability data, use the liabilities/get endpoint."
        )
    )
    label: str = "Derived Liabilities Summary (from stored transactions)"

    class Config:
        frozen = True


# =============================================================================
# GOVCON / DCAA MAPPING MODELS (Phase 10A)
# =============================================================================

class GovConSectionMapping(BaseModel):
    """
    Static DCAA reference mapping for a single export section.

    NO inference, NO compliance claims - purely descriptive references.
    """

    dcaa_refs: List[str] = Field(
        ...,
        description="Static list of DCAA/FAR references applicable to this section"
    )
    description: str = Field(
        ...,
        description="Descriptive text explaining section relevance (no compliance claims)"
    )

    class Config:
        frozen = True


class GovConMapping(BaseModel):
    """
    Static, versioned GovCon / DCAA mapping for audit export manifest.

    CANONICAL CONSTRAINTS:
    - Static mapping only (no dynamic logic)
    - Versioned explicitly
    - NO inference, NO scoring, NO compliance claims
    - Included only if corresponding section is present

    This mapping classifies exported evidence without interpretation.
    """

    standard: str = Field(
        default="DCAA",
        description="Compliance standard (always DCAA for GovCon)"
    )
    version: str = Field(
        ...,
        description="Mapping version (e.g., '2024.1')"
    )
    sections: Dict[str, GovConSectionMapping] = Field(
        ...,
        description="Per-section DCAA reference mappings (only for included sections)"
    )

    class Config:
        frozen = True


# =============================================================================
# MANIFEST AND HASHES MODELS
# =============================================================================

class SectionCounts(BaseModel):
    """Counts for each section in the export."""

    statements: int = 0
    receipts: int = 0
    assets_accounts: int = 0
    liabilities_accounts: int = 0

    class Config:
        frozen = True


class DataSources(BaseModel):
    """Data source indicators for each section."""

    statements: str = "local_database"
    assets: str = "derived_from_transactions"
    liabilities: str = "derived_from_transactions"

    class Config:
        frozen = True


class ManifestV2(BaseModel):
    """
    Manifest v2 for audit export packages.

    REQUIRED fields per spec:
    - manifest_version: Must be "v2"
    - org_id: Organization identifier
    - generated_at: UTC ISO8601 timestamp
    - included_sections: Array of included section names
    - counts: Per-section counts
    - request_id: Request trace identifier
    """

    manifest_version: Literal["v2"] = "v2"
    org_id: str
    generated_at: str
    generated_by: str
    request_id: str
    included_sections: List[str]
    counts: Dict[str, int]
    files: List[str]
    export_type: str = "audit_export_v2"
    data_sources: Dict[str, str]
    compliance_notes: List[str] = Field(
        default_factory=lambda: [
            "This export uses locally stored data only.",
            "No live Plaid API calls were made during export generation.",
            "For authoritative financial data, use the respective Plaid product endpoints.",
        ]
    )

    class Config:
        frozen = True


class HashesV2(BaseModel):
    """
    Hashes v2 for audit export integrity verification.

    REQUIRED fields per spec:
    - algorithm: Hash algorithm used (SHA-256)
    - file_hashes: SHA-256 for every file in the export
    - Hash of manifest.json included
    - Deterministic contents order
    """

    generated_at: str
    algorithm: Literal["SHA-256"] = "SHA-256"
    file_hashes: Dict[str, str]
    contents_order: List[str]
    contents_order_hash: str

    class Config:
        frozen = True


# =============================================================================
# RESPONSE MODELS
# =============================================================================

class ExportPreviewData(BaseModel):
    """Preview data for audit export."""

    organization_id: str
    preview_generated_at: str
    available_data: Dict[str, Any]
    export_structure: List[str]
    notes: List[str]

    class Config:
        frozen = True


class ExportPreviewResponse(BaseModel):
    """Response for audit export preview endpoint."""

    status: str = "ok"
    data: ExportPreviewData
    message: str
    request_id: str
    timestamp: str

    class Config:
        frozen = True
