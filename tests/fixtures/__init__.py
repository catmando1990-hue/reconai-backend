"""
Test fixtures for reconai-backend.

Provides canonical factories and schema assertion helpers.
All tests MUST use these fixtures - no inline mocks allowed.
"""

from .core_state_factory import (
    # Schema assertion
    SchemaValidationError,
    assert_valid_core_state,
    # Factory
    core_state_factory,
    # Preset factories
    empty_org_state,
    partial_org_state,
    full_org_state,
    # Sync state builders
    with_sync_running,
    with_sync_failed,
    with_stale_data,
)

from .cfo_state_factory import (
    # Schema assertion
    CfoSchemaValidationError,
    assert_valid_cfo_state,
    # Evidence and lifecycle builders
    evidence_factory,
    empty_evidence,
    lifecycle_factory,
    # CFO Overview factories
    cfo_overview_factory,
    success_cfo_overview,
    partial_cfo_overview,
    failed_cfo_overview,
    no_data_cfo_overview,
    # CFO Forecast factories
    cfo_forecast_factory,
    success_cfo_forecast,
    low_confidence_cfo_forecast,
    # CFO Exceptions factories
    cfo_exceptions_factory,
    success_cfo_exceptions,
    financial_exception_factory,
)

from .intelligence_state_factory import (
    # Schema assertion
    IntelligenceSchemaValidationError,
    assert_valid_intelligence_state,
    # Evidence and lifecycle builders
    evidence_factory as intelligence_evidence_factory,
    empty_evidence as intelligence_empty_evidence,
    lifecycle_factory as intelligence_lifecycle_factory,
    # Classification builders
    classification_result_factory,
    # Intelligence Classify factories
    intelligence_classify_factory,
    success_intelligence_classify,
    partial_intelligence_classify,
    failed_intelligence_classify,
    no_data_intelligence_classify,
    low_confidence_intelligence_classify,
    # Intelligence Overlay factories
    intelligence_overlay_factory,
    success_intelligence_overlay,
)

from .govcon_state_factory import (
    # Schema assertion
    GovConSchemaValidationError,
    assert_valid_govcon_state,
    # Lifecycle and evidence builders
    govcon_lifecycle_factory,
    govcon_evidence_factory,
    govcon_empty_evidence,
    # Classification builders
    govcon_classification_factory,
    govcon_transaction_overlay_factory,
    # Transactions response factories
    govcon_transactions_factory,
    success_govcon_transactions,
    partial_govcon_transactions,
    failed_govcon_transactions,
    no_data_govcon_transactions,
    pending_review_govcon_transactions,
    # Export preview factories
    export_preview_item_factory,
    govcon_export_preview_factory,
    success_export_preview,
    blocked_export_preview,
    failed_export_preview,
)

__all__ = [
    # Core State
    "SchemaValidationError",
    "assert_valid_core_state",
    "core_state_factory",
    "empty_org_state",
    "partial_org_state",
    "full_org_state",
    "with_sync_running",
    "with_sync_failed",
    "with_stale_data",
    # CFO State
    "CfoSchemaValidationError",
    "assert_valid_cfo_state",
    "evidence_factory",
    "empty_evidence",
    "lifecycle_factory",
    "cfo_overview_factory",
    "success_cfo_overview",
    "partial_cfo_overview",
    "failed_cfo_overview",
    "no_data_cfo_overview",
    "cfo_forecast_factory",
    "success_cfo_forecast",
    "low_confidence_cfo_forecast",
    "cfo_exceptions_factory",
    "success_cfo_exceptions",
    "financial_exception_factory",
    # Intelligence State
    "IntelligenceSchemaValidationError",
    "assert_valid_intelligence_state",
    "intelligence_evidence_factory",
    "intelligence_empty_evidence",
    "intelligence_lifecycle_factory",
    "classification_result_factory",
    "intelligence_classify_factory",
    "success_intelligence_classify",
    "partial_intelligence_classify",
    "failed_intelligence_classify",
    "no_data_intelligence_classify",
    "low_confidence_intelligence_classify",
    "intelligence_overlay_factory",
    "success_intelligence_overlay",
    # GovCon State
    "GovConSchemaValidationError",
    "assert_valid_govcon_state",
    "govcon_lifecycle_factory",
    "govcon_evidence_factory",
    "govcon_empty_evidence",
    "govcon_classification_factory",
    "govcon_transaction_overlay_factory",
    "govcon_transactions_factory",
    "success_govcon_transactions",
    "partial_govcon_transactions",
    "failed_govcon_transactions",
    "no_data_govcon_transactions",
    "pending_review_govcon_transactions",
    "export_preview_item_factory",
    "govcon_export_preview_factory",
    "success_export_preview",
    "blocked_export_preview",
    "failed_export_preview",
]
