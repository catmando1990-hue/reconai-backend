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

__all__ = [
    "SchemaValidationError",
    "assert_valid_core_state",
    "core_state_factory",
    "empty_org_state",
    "partial_org_state",
    "full_org_state",
    "with_sync_running",
    "with_sync_failed",
    "with_stale_data",
]
