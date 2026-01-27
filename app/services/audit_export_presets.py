# app/services/audit_export_presets.py
"""
GovCon Packet Preset Resolver / Assembler (Phase 12A)

Maps preset identifiers to required sections and delegates to the
canonical audit_export_builder_v2 for ZIP assembly.

CANONICAL LAWS:
- Static preset definitions only (hardcoded, no database)
- New presets = code change
- No compliance claims, no scoring, no analytics
- Delegates to builder for all ZIP/signing/hashing logic
- No Plaid calls
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.schemas.audit_export_v2 import PacketBlock
from app.schemas.audit_export_presets import PresetType
from app.services.audit_export_builder_v2 import BuildResult, build_audit_export_v2


# =============================================================================
# PRESET REGISTRY (Static, Hardcoded)
# =============================================================================
# Each entry maps a preset name to:
#   - description: Human-readable label (no compliance claims)
#   - includes: List of section names included in the preset
#   - include_statements / include_assets / include_liabilities: Section flags
#
# New presets are added here + a corresponding PresetType enum value.

PRESET_REGISTRY: Dict[str, Dict[str, Any]] = {
    PresetType.SF1408_PRE_AWARD.value: {
        "description": "Pre-award evidence bundle aligned to SF 1408.",
        "includes": ["statements", "assets", "liabilities"],
        "include_statements": True,
        "include_assets": True,
        "include_liabilities": True,
    },
}


def get_available_presets() -> List[str]:
    """Return list of available preset names."""
    return list(PRESET_REGISTRY.keys())


def resolve_preset(preset_name: str) -> Optional[Dict[str, Any]]:
    """
    Look up a preset by name.

    Args:
        preset_name: Preset identifier (e.g., 'sf1408_pre_award')

    Returns:
        Preset config dict if found, None if unknown preset
    """
    return PRESET_REGISTRY.get(preset_name)


def build_packet_block(preset_name: str, preset_config: Dict[str, Any]) -> PacketBlock:
    """
    Build a PacketBlock from a resolved preset config.

    Args:
        preset_name: Preset identifier
        preset_config: Resolved preset config from registry

    Returns:
        Strongly typed PacketBlock for manifest inclusion
    """
    return PacketBlock(
        preset=preset_name,
        description=preset_config["description"],
        includes=preset_config["includes"],
    )


def assemble_preset_export(
    organization_id: str,
    user_id: str,
    request_id: str,
    preset_name: str,
    preset_config: Dict[str, Any],
    statement_from_date: Optional[str] = None,
    statement_to_date: Optional[str] = None,
) -> BuildResult:
    """
    Assemble a preset-based export by delegating to the canonical builder.

    Args:
        organization_id: Organization to export data for
        user_id: User generating the export
        request_id: Request trace identifier
        preset_name: Preset identifier
        preset_config: Resolved preset config from registry
        statement_from_date: Optional start date for statement period filter
        statement_to_date: Optional end date for statement period filter

    Returns:
        BuildResult from the canonical builder (ZIP, manifest, hashes, etc.)
    """
    packet_block = build_packet_block(preset_name, preset_config)

    return build_audit_export_v2(
        organization_id=organization_id,
        user_id=user_id,
        request_id=request_id,
        include_statements=preset_config["include_statements"],
        include_assets=preset_config["include_assets"],
        include_liabilities=preset_config["include_liabilities"],
        packet=packet_block,
        statement_from_date=statement_from_date,
        statement_to_date=statement_to_date,
    )
