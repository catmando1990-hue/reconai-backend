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
]
