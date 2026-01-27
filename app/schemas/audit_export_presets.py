# app/schemas/audit_export_presets.py
"""
Pydantic Models for GovCon Packet Presets (Phase 12A)

Explicit typing for preset-based audit export requests.
All models are immutable (frozen=True) to prevent accidental mutation.

CANONICAL LAWS:
- No mutations after creation
- All fields explicitly typed
- Validation at boundaries
- PresetType enum for strong typing of preset identifiers
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# =============================================================================
# PRESET TYPE ENUM
# =============================================================================

class PresetType(str, Enum):
    """
    Strongly typed preset identifiers.

    Each value maps to a hardcoded entry in the preset registry.
    New presets = code change (add enum value + registry entry).
    """

    SF1408_PRE_AWARD = "sf1408_pre_award"


# =============================================================================
# REQUEST MODELS
# =============================================================================

class StatementPeriod(BaseModel):
    """Date range filter for statements in preset exports."""

    from_date: str = Field(
        ...,
        alias="from",
        description="Start date (YYYY-MM-DD) for statement period filter"
    )
    to_date: str = Field(
        ...,
        alias="to",
        description="End date (YYYY-MM-DD) for statement period filter"
    )

    class Config:
        frozen = True
        populate_by_name = True


class PresetOptions(BaseModel):
    """Options for preset-based export generation."""

    statement_period: Optional[StatementPeriod] = Field(
        default=None,
        description="Optional date range filter for statements"
    )
    asset_snapshot_id: Optional[str] = Field(
        default=None,
        description="Reserved for future use. Asset snapshots are derived on-demand."
    )

    class Config:
        frozen = True


class PresetRequest(BaseModel):
    """Request body for generating a preset-based audit export."""

    preset: str = Field(
        ...,
        description="Preset name (e.g., 'sf1408_pre_award')"
    )
    options: Optional[PresetOptions] = Field(
        default=None,
        description="Optional preset-specific options"
    )

    class Config:
        frozen = True
