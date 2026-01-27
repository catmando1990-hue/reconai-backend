# app/routers/audit_export_presets_v2.py
"""
Audit Export v2 — GovCon Packet Presets API (Phase 12A)

Preset-based export endpoint that assembles pre-defined evidence bundles
using existing Audit Export v2 builder + signing.

CANONICAL LAWS:
- Manual execution only (no cron, triggers, or automation)
- Read-only (no mutations to source data)
- No new Plaid calls (uses stored/derived data only)
- RBAC fail-closed (403 if permission denied)
- Org-isolated (only export data for authenticated organization)
- Full audit logging on exports
- No background workers or schedulers
- No compliance claims, no scoring, no analytics

FRONTEND CONTRACT:
    POST /api/audit-exports/v2/presets
        -> Returns JSON with export_id, generated_at, download_url, packet metadata
    Download via existing GET /api/audit-exports/v2/download?export_id={id}

REQUIRED PERMISSION: admin or org:admin
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from app.auth_context import get_current_context, get_current_organization_id, AuthContext
from app.schemas.audit_export_presets import PresetRequest
from app.services.audit_export_presets import (
    get_available_presets,
    resolve_preset,
    assemble_preset_export,
)


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/audit-exports", tags=["audit-exports-v2", "governance"])


# =============================================================================
# AUDIT EVENT CONSTANTS
# =============================================================================

AUDIT_EVENT_V2_ACCESS_DENIED = "audit_export_v2_access_denied"
AUDIT_EVENT_V2_GOVCON_MAPPED = "audit_export_v2_govcon_mapped"
AUDIT_EVENT_V2_SIGNED = "audit_export_v2_signed"
AUDIT_EVENT_V2_SIGNATURE_VERIFIED = "audit_export_v2_signature_verified"
AUDIT_EVENT_V2_PRESET_REQUESTED = "audit_export_preset_requested"
AUDIT_EVENT_V2_PRESET_GENERATED = "audit_export_preset_generated"


# =============================================================================
# IN-MEMORY EXPORT CACHE (shared with audit_exports_v2 router)
# =============================================================================
# Preset exports use the same cache + download endpoint as regular v2 exports.
# Import from the existing router to share the cache.

from app.routers.audit_exports_v2 import (
    _cache_export,
    CachedExport,
)

EXPORT_CACHE_TTL_SECONDS = 600  # 10 minutes


# =============================================================================
# HELPERS
# =============================================================================

def _validate_request_id(request_id: Optional[str]) -> str:
    """Validate X-Request-ID header. FAIL-CLOSED: Generate if missing."""
    if request_id:
        try:
            uuid.UUID(request_id)
            return request_id
        except (ValueError, TypeError):
            pass
    return f"req_{uuid.uuid4().hex[:16]}"


def _build_error_response(
    status_code: int,
    error: str,
    message: str,
    request_id: str,
) -> JSONResponse:
    """Build error JSONResponse with canonical envelope."""
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "error",
            "data": {},
            "error": error,
            "message": message,
            "request_id": request_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        headers={"X-Request-ID": request_id},
    )


def _assert_admin(ctx: AuthContext, request_id: str) -> None:
    """
    Ensure user has admin privileges (FAIL-CLOSED).

    Accepts: admin, org:admin, owner roles.
    Raises HTTPException 403 if not authorized.
    """
    clerk_metadata = ctx.get("clerk_metadata") or {}
    clerk_role = clerk_metadata.get("role", "")

    if clerk_role in ["admin", "org:admin", "owner"]:
        return

    permissions = ctx.get("permissions")
    if permissions:
        db_role = permissions.get("role", "")
        if db_role in ["admin", "owner"]:
            return

    raise HTTPException(
        status_code=403,
        detail={
            "error": "permission_denied",
            "message": "Admin access required. Only admin or org:admin roles can generate audit exports.",
            "request_id": request_id,
        }
    )


def _log_audit_event(
    user_id: str,
    organization_id: str,
    event_type: str,
    request_id: str,
    payload: dict,
) -> None:
    """
    Log audit event for export operations.

    Non-blocking: errors are logged but don't fail the request.
    """
    from app.services.audit_store import AuditEventInput, insert_audit_event

    try:
        audit_input = AuditEventInput(
            actor_id=user_id,
            event_type=event_type,
            entity_type="audit_exports_v2",
            entity_id=organization_id,
            payload={
                **payload,
                "request_id": request_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        insert_audit_event(audit_input)
    except Exception as e:
        logger.warning(f"Audit logging failed for {event_type}: {e}")


# =============================================================================
# ENDPOINT
# =============================================================================

@router.post("/v2/presets", tags=["audit-exports-v2", "governance"])
async def generate_preset_export(
    payload: PresetRequest,
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    organization_id: str = Depends(get_current_organization_id),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
) -> JSONResponse:
    """
    Generate a preset-based Audit Export v2 — GovCon Packet.

    Assembles a pre-defined evidence bundle using existing v2 builder + signing.
    Presets are hardcoded static definitions (e.g., sf1408_pre_award).

    MANUAL EXECUTION ONLY - invoked explicitly by authorized users.
    NO BACKGROUND WORKERS - assembled in-memory during request.
    NO PLAID CALLS - uses stored/derived data only.
    NO COMPLIANCE CLAIMS - presets select sections, nothing more.

    Response:
        {
            "status": "ok",
            "data": {
                "export_id": "exp_...",
                "generated_at": "ISO8601",
                "download_url": "/api/audit-exports/v2/download?export_id=exp_...",
                "filename": "...",
                "manifest_hash": "sha256...",
                "preset": "sf1408_pre_award",
                "packet": { "preset": "...", "description": "...", "includes": [...] },
                "included_sections": [...],
                "counts": {...},
                "govcon_mapping": {...} | null,
                "integrity": {...} | null,
                "signing_applied": bool
            }
        }

    Security:
        - Requires admin or org:admin role (FAIL-CLOSED)
        - Org-isolated: Only exports data for authenticated organization
        - Audit logged: audit_export_preset_requested, audit_export_preset_generated
        - Structured error envelope with request_id
    """
    request_id = _validate_request_id(x_request_id)
    user_id = ctx["user_id"]

    # ==========================================================================
    # RBAC ENFORCEMENT (FAIL-CLOSED)
    # ==========================================================================
    try:
        _assert_admin(ctx, request_id)
    except HTTPException as e:
        _log_audit_event(
            user_id=user_id,
            organization_id=organization_id,
            event_type=AUDIT_EVENT_V2_ACCESS_DENIED,
            request_id=request_id,
            payload={
                "reason": "insufficient_permissions",
                "org_id": organization_id,
                "preset": payload.preset,
            }
        )
        raise e

    # ==========================================================================
    # VALIDATE PRESET
    # ==========================================================================
    preset_name = payload.preset
    preset_config = resolve_preset(preset_name)
    if preset_config is None:
        return _build_error_response(
            status_code=400,
            error="invalid_preset",
            message=f"Unknown preset: '{preset_name}'. Available presets: {get_available_presets()}",
            request_id=request_id,
        )

    # ==========================================================================
    # AUDIT LOG: PRESET REQUESTED
    # ==========================================================================
    _log_audit_event(
        user_id=user_id,
        organization_id=organization_id,
        event_type=AUDIT_EVENT_V2_PRESET_REQUESTED,
        request_id=request_id,
        payload={
            "org_id": organization_id,
            "preset": preset_name,
            "options": payload.options.model_dump() if payload.options else None,
        }
    )

    try:
        # ==========================================================================
        # RESOLVE PRESET OPTIONS
        # ==========================================================================
        statement_from_date = None
        statement_to_date = None
        if payload.options and payload.options.statement_period:
            statement_from_date = payload.options.statement_period.from_date
            statement_to_date = payload.options.statement_period.to_date

        # ==========================================================================
        # ASSEMBLE EXPORT (delegates to preset service → builder)
        # ==========================================================================
        result = assemble_preset_export(
            organization_id=organization_id,
            user_id=user_id,
            request_id=request_id,
            preset_name=preset_name,
            preset_config=preset_config,
            statement_from_date=statement_from_date,
            statement_to_date=statement_to_date,
        )

        # Get manifest hash
        manifest_hash = result.file_hashes.get("manifest.json", "")

        # ==========================================================================
        # AUDIT LOG: GOVCON MAPPING (Phase 10A)
        # ==========================================================================
        govcon_mapping_data = None
        if result.govcon_mapping_applied:
            govcon_mapping_data = result.manifest.get("govcon_mapping", {})
            _log_audit_event(
                user_id=user_id,
                organization_id=organization_id,
                event_type=AUDIT_EVENT_V2_GOVCON_MAPPED,
                request_id=request_id,
                payload={
                    "org_id": organization_id,
                    "preset": preset_name,
                    "mapping_standard": govcon_mapping_data.get("standard"),
                    "mapping_version": govcon_mapping_data.get("version"),
                    "mapped_sections": list(govcon_mapping_data.get("sections", {}).keys()),
                }
            )

        # ==========================================================================
        # AUDIT LOG: SIGNING (Phase 11A)
        # ==========================================================================
        if result.signing_applied:
            integrity = result.manifest.get("integrity", {})
            _log_audit_event(
                user_id=user_id,
                organization_id=organization_id,
                event_type=AUDIT_EVENT_V2_SIGNED,
                request_id=request_id,
                payload={
                    "org_id": organization_id,
                    "preset": preset_name,
                    "chain_root_prefix": integrity.get("hash_chain", {}).get("root", "")[:16],
                    "key_id": integrity.get("signature", {}).get("key_id"),
                    "algorithm": "ed25519",
                }
            )
            _log_audit_event(
                user_id=user_id,
                organization_id=organization_id,
                event_type=AUDIT_EVENT_V2_SIGNATURE_VERIFIED,
                request_id=request_id,
                payload={
                    "org_id": organization_id,
                    "preset": preset_name,
                    "verification": "self_check_passed",
                    "key_id": integrity.get("signature", {}).get("key_id"),
                }
            )

        # ==========================================================================
        # CACHE EXPORT FOR DOWNLOAD
        # ==========================================================================
        export_id = f"exp_{uuid.uuid4().hex[:16]}"
        zip_bytes = result.zip_buffer.read()

        _cache_export(export_id, CachedExport(
            zip_bytes=zip_bytes,
            filename=result.filename,
            manifest_hash=manifest_hash,
            organization_id=organization_id,
        ))

        generated_at = result.manifest.get("generated_at", datetime.now(timezone.utc).isoformat())
        download_url = f"/api/audit-exports/v2/download?export_id={export_id}"

        # ==========================================================================
        # AUDIT LOG: PRESET GENERATED
        # ==========================================================================
        _log_audit_event(
            user_id=user_id,
            organization_id=organization_id,
            event_type=AUDIT_EVENT_V2_PRESET_GENERATED,
            request_id=request_id,
            payload={
                "org_id": organization_id,
                "preset": preset_name,
                "export_id": export_id,
                "manifest_hash_prefix": manifest_hash[:16] + "..." if manifest_hash else None,
                "signing_applied": result.signing_applied,
            }
        )

        # Build packet data for response
        packet_data = {
            "preset": preset_name,
            "description": preset_config["description"],
            "includes": preset_config["includes"],
        }

        # ==========================================================================
        # RETURN JSON METADATA
        # ==========================================================================
        return JSONResponse(
            status_code=200,
            content={
                "status": "ok",
                "data": {
                    "export_id": export_id,
                    "generated_at": generated_at,
                    "download_url": download_url,
                    "filename": result.filename,
                    "manifest_hash": manifest_hash,
                    "preset": preset_name,
                    "packet": packet_data,
                    "included_sections": result.manifest.get("included_sections", []),
                    "counts": result.manifest.get("counts", {}),
                    "govcon_mapping": govcon_mapping_data,
                    "integrity": result.manifest.get("integrity"),
                    "signing_applied": result.signing_applied,
                },
                "message": f"Preset export '{preset_name}' generated successfully. Use download_url to retrieve the ZIP.",
                "request_id": request_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            headers={
                "X-Request-ID": request_id,
                "X-Export-Manifest-Hash": manifest_hash,
                "X-Export-Type": "audit_export_v2",
                "X-Export-Preset": preset_name,
            },
        )

    except Exception as e:
        logger.error(f"Preset export generation failed: {e}")
        return _build_error_response(
            status_code=500,
            error="preset_export_generation_failed",
            message="Failed to generate preset export. Please try again.",
            request_id=request_id,
        )
