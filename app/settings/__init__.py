# app/settings/__init__.py
"""
Settings Contract Module

Exports canonical contract versioning and validation utilities
for all settings-related API endpoints.
"""

from app.settings.contract import (
    SETTINGS_CONTRACT_VERSION,
    VALID_SETTINGS_LIFECYCLE_STATUSES,
    SettingsLifecycleStatus,
    SettingsLifecycle,
    SettingsMetadata,
    create_settings_lifecycle,
    create_settings_metadata,
    wrap_settings_response,
)

__all__ = [
    "SETTINGS_CONTRACT_VERSION",
    "VALID_SETTINGS_LIFECYCLE_STATUSES",
    "SettingsLifecycleStatus",
    "SettingsLifecycle",
    "SettingsMetadata",
    "create_settings_lifecycle",
    "create_settings_metadata",
    "wrap_settings_response",
]
