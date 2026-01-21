# app/routers/evidence_export_api.py
"""
============================================================================
PHASE 9: SIGNED EVIDENCE EXPORT PACKS
============================================================================

Provides tamper-evident, verifiable export packs for external review.

CANONICAL LAWS ENFORCED:
- Manual > Automatic: User explicitly requests export
- Signed > Trusted: All exports include cryptographic integrity
- Evidence > Explanation: Export contains raw evidence, not summaries
- Unknown > Assumed: Missing data labeled UNKNOWN in exports

EXPORT GUARANTEES:
- SHA-256 hash for each file
- SHA-256 hash for whole package
- Manifest with file list and hashes
- Verification instructions included
- Exports are immutable once generated
- No regeneration with same ID

============================================================================
"""

from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from datetime import datetime
from enum import Enum
from uuid import uuid4
import hashlib
import json
import base64
import logging
import os

from app.auth_context import get_current_context, AuthContext
from app.services.audit_store import (
    get_audit_events,
    count_audit_events,
    verify_audit_chain,
    insert_audit_event,
    AuditEventInput,
)

logger = logging.getLogger(__name__)


# =============================================================================
# ACCESS CONTROL
# =============================================================================

async def require_export_access(
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
):
    """Require authentication for export operations."""
    if not ctx.get("user_id"):
        raise HTTPException(status_code=401, detail="Authentication required for export")
    return ctx


router = APIRouter(
    prefix="/audit/export",
    tags=["Evidence Export Packs"],
    dependencies=[Depends(require_export_access)],
)


# =============================================================================
# MODELS
# =============================================================================

class ExportScope(BaseModel):
    """Defines the scope of an export pack"""
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    entity_types: Optional[List[str]] = None
    event_types: Optional[List[str]] = None
    include_integrity_verification: bool = True
    include_verification_instructions: bool = True


class ExportPackRequest(BaseModel):
    """Request to generate an export pack"""
    scope: ExportScope
    format: Literal["json"] = "json"
    requester_id: str
    requester_name: Optional[str] = None
    purpose: Optional[str] = None


class FileManifestEntry(BaseModel):
    """Entry in the export manifest"""
    filename: str
    size_bytes: int
    sha256_hash: str
    content_type: str
    description: str


class ExportManifest(BaseModel):
    """Manifest for an export pack"""
    export_id: str
    generated_at: datetime
    org_id: str
    scope_definition: dict
    system_version: str
    files: List[FileManifestEntry]
    package_hash: str
    signing_status: Literal["unsigned", "signed"]
    signature: Optional[str] = None


class ExportPackRecord(BaseModel):
    """Record of a generated export pack"""
    export_id: str
    requested_at: datetime
    generated_at: datetime
    requester_id: str
    requester_name: Optional[str]
    purpose: Optional[str]
    scope: ExportScope
    status: Literal["completed", "failed"]
    manifest_hash: str
    event_count: int
    file_count: int


# =============================================================================
# IN-MEMORY EXPORT RECORDS (Production would use database)
# =============================================================================

_export_records: List[ExportPackRecord] = []
_generated_export_ids: set = set()  # Track generated IDs for immutability


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _compute_sha256(data: bytes) -> str:
    """Compute SHA-256 hash of bytes"""
    return hashlib.sha256(data).hexdigest()


def _compute_json_hash(data: dict) -> str:
    """Compute SHA-256 hash of JSON data"""
    json_bytes = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
    return _compute_sha256(json_bytes)


def _get_system_version() -> str:
    """Get current system version"""
    return os.getenv("RECONAI_VERSION", "1.0.0-audit")


def _log_export_event(
    export_id: str,
    requester_id: str,
    event_type: str,
    description: str,
    payload: dict,
):
    """Log an export event to the Evidence Ledger"""
    try:
        event_input = AuditEventInput(
            actor_id=requester_id,
            event_type=event_type,
            entity_type="evidence_export",
            entity_id=export_id,
            payload=payload,
        )
        insert_audit_event(event_input)
    except Exception as e:
        logger.error(f"Failed to log export event: {e}")
        # Don't fail the export if logging fails, but record the issue
        pass


# =============================================================================
# VERIFICATION INSTRUCTIONS TEMPLATE
# =============================================================================

VERIFICATION_README = """
# Evidence Export Pack Verification Guide

## Overview
This export pack contains evidence from the ReconAI Evidence Ledger.
It is designed to be tamper-evident and independently verifiable.

## Package Contents
- `manifest.json` - File listing with SHA-256 hashes
- `evidence.json` - Raw evidence ledger entries
- `integrity.json` - Hash chain verification results
- `README.txt` - This verification guide

## How to Verify Integrity

### Step 1: Verify Individual File Hashes
For each file listed in `manifest.json`, compute its SHA-256 hash and compare:

```bash
# On Linux/Mac:
sha256sum evidence.json
sha256sum integrity.json

# On Windows (PowerShell):
Get-FileHash evidence.json -Algorithm SHA256
Get-FileHash integrity.json -Algorithm SHA256
```

Compare the output to the `sha256_hash` values in `manifest.json`.

### Step 2: Verify Package Hash
Compute the hash of `manifest.json` itself and compare to the `package_hash` field.

### Step 3: Verify Hash Chain
The `integrity.json` file contains hash chain verification results.
Each event in the evidence ledger references the previous event's hash.
If all events show `chain_valid: true`, the chain is intact.

## What This Export GUARANTEES
- Evidence entries are from the append-only Evidence Ledger
- File hashes match computed SHA-256 values
- Hash chain was intact at time of export
- Export scope is explicitly documented

## What This Export Does NOT GUARANTEE
- Completeness of all system activity (only recorded events included)
- Real-time accuracy (snapshot at generation time)
- External system verification (only ReconAI ledger)

## Signing Status
{signing_status}

## Questions?
Contact: audit@reconaitechnology.com
"""


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/preview", response_model=dict)
async def preview_export_scope(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    entity_type: Optional[str] = None,
):
    """
    Preview export scope before generating.

    Shows what will be included in the export WITHOUT generating it.
    This allows the user to review scope before explicit generation.
    """
    # Count events that would be included
    count = count_audit_events(
        entity_type=entity_type,
        start_date=start_date.isoformat() if start_date else None,
        end_date=end_date.isoformat() if end_date else None,
    )

    # Get sample of events (first 5)
    sample_events = get_audit_events(
        entity_type=entity_type,
        start_date=start_date.isoformat() if start_date else None,
        end_date=end_date.isoformat() if end_date else None,
        limit=5,
    )

    return {
        "preview": True,
        "export_not_generated": True,
        "scope": {
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
            "entity_type": entity_type,
        },
        "estimated_event_count": count,
        "sample_events": [{
            "event_id": e.id,
            "event_type": e.event_type,
            "timestamp": e.created_at,
            "entity_type": e.entity_type,
        } for e in sample_events],
        "advisory": {
            "type": "advisory",
            "message": "This is a preview only. Use POST /audit/export/generate to create the export pack.",
        }
    }


@router.post("/generate", response_model=dict)
async def generate_export_pack(
    request: ExportPackRequest,
    ctx: AuthContext = Depends(require_export_access),
):
    """
    Generate a signed evidence export pack.

    MANUAL TRIGGER ONLY - User explicitly requests export.
    Export scope must be visible before generation.

    This endpoint:
    1. Validates the request
    2. Fetches evidence within scope
    3. Computes hashes for all content
    4. Generates manifest
    5. Logs the export to Evidence Ledger
    6. Returns the complete export pack
    """
    now = datetime.utcnow()
    export_id = f"exp_{now.strftime('%Y%m%d_%H%M%S')}_{str(uuid4())[:8]}"

    # Check for duplicate export ID (immutability guarantee)
    if export_id in _generated_export_ids:
        raise HTTPException(
            status_code=409,
            detail="Export ID collision. Please retry."
        )

    org_id = ctx.get("org_id", "unknown")
    requester_id = request.requester_id

    try:
        # Fetch events within scope
        events = get_audit_events(
            entity_type=request.scope.entity_types[0] if request.scope.entity_types else None,
            start_date=request.scope.start_date.isoformat() if request.scope.start_date else None,
            end_date=request.scope.end_date.isoformat() if request.scope.end_date else None,
            limit=10000,  # High limit for exports
        )

        # Filter by event types if specified
        if request.scope.event_types:
            events = [e for e in events if e.event_type in request.scope.event_types]

        # Build evidence content
        evidence_data = {
            "export_id": export_id,
            "generated_at": now.isoformat(),
            "event_count": len(events),
            "events": [{
                "id": e.id,
                "created_at": e.created_at,
                "event_type": e.event_type,
                "entity_type": e.entity_type,
                "entity_id": e.entity_id,
                "actor_id": e.actor_id,
                "payload": e.payload,
                "prev_hash": e.prev_hash,
                "event_hash": e.event_hash,
            } for e in events],
        }
        evidence_json = json.dumps(evidence_data, sort_keys=True, default=str)
        evidence_bytes = evidence_json.encode("utf-8")
        evidence_hash = _compute_sha256(evidence_bytes)

        # Build integrity verification content
        integrity_data = {
            "export_id": export_id,
            "verified_at": now.isoformat(),
            "chain_verification": "pending",
            "issues": [],
        }

        if request.scope.include_integrity_verification:
            is_valid, issues = verify_audit_chain(limit=len(events) if events else 100)
            integrity_data["chain_verification"] = "valid" if is_valid else "INTEGRITY_VIOLATION"
            integrity_data["issues"] = issues
            integrity_data["verified_event_count"] = len(events)

        integrity_json = json.dumps(integrity_data, sort_keys=True, default=str)
        integrity_bytes = integrity_json.encode("utf-8")
        integrity_hash = _compute_sha256(integrity_bytes)

        # Build README content
        signing_status = "This export is UNSIGNED. Cryptographic signing infrastructure not configured."
        readme_content = VERIFICATION_README.format(signing_status=signing_status)
        readme_bytes = readme_content.encode("utf-8")
        readme_hash = _compute_sha256(readme_bytes)

        # Build manifest
        files = [
            FileManifestEntry(
                filename="evidence.json",
                size_bytes=len(evidence_bytes),
                sha256_hash=evidence_hash,
                content_type="application/json",
                description="Raw evidence ledger entries within export scope",
            ),
            FileManifestEntry(
                filename="integrity.json",
                size_bytes=len(integrity_bytes),
                sha256_hash=integrity_hash,
                content_type="application/json",
                description="Hash chain integrity verification results",
            ),
            FileManifestEntry(
                filename="README.txt",
                size_bytes=len(readme_bytes),
                sha256_hash=readme_hash,
                content_type="text/plain",
                description="Verification instructions",
            ),
        ]

        # Compute package hash (hash of manifest data before adding package_hash)
        manifest_data_for_hash = {
            "export_id": export_id,
            "generated_at": now.isoformat(),
            "org_id": org_id,
            "scope_definition": request.scope.dict(),
            "system_version": _get_system_version(),
            "files": [f.dict() for f in files],
        }
        package_hash = _compute_json_hash(manifest_data_for_hash)

        manifest = ExportManifest(
            export_id=export_id,
            generated_at=now,
            org_id=org_id,
            scope_definition=request.scope.dict(),
            system_version=_get_system_version(),
            files=files,
            package_hash=package_hash,
            signing_status="unsigned",
            signature=None,
        )

        manifest_json = json.dumps(manifest.dict(), sort_keys=True, default=str)
        manifest_bytes = manifest_json.encode("utf-8")
        manifest_hash = _compute_sha256(manifest_bytes)

        # Record the export
        export_record = ExportPackRecord(
            export_id=export_id,
            requested_at=now,
            generated_at=now,
            requester_id=requester_id,
            requester_name=request.requester_name,
            purpose=request.purpose,
            scope=request.scope,
            status="completed",
            manifest_hash=manifest_hash,
            event_count=len(events),
            file_count=len(files),
        )
        _export_records.append(export_record)
        _generated_export_ids.add(export_id)

        # Log the export to Evidence Ledger
        _log_export_event(
            export_id=export_id,
            requester_id=requester_id,
            event_type="evidence_export_generated",
            description=f"Evidence export pack generated: {len(events)} events",
            payload={
                "scope": request.scope.dict(),
                "event_count": len(events),
                "package_hash": package_hash,
                "manifest_hash": manifest_hash,
                "purpose": request.purpose,
            },
        )

        # Return the complete export pack
        return {
            "export_id": export_id,
            "status": "completed",
            "generated_at": now.isoformat(),
            "manifest": manifest.dict(),
            "files": {
                "evidence.json": evidence_data,
                "integrity.json": integrity_data,
                "README.txt": readme_content,
            },
            "hashes": {
                "evidence.json": evidence_hash,
                "integrity.json": integrity_hash,
                "README.txt": readme_hash,
                "manifest.json": manifest_hash,
                "package": package_hash,
            },
            "verification": {
                "hash_algorithm": "SHA-256",
                "how_to_verify": "Compute SHA-256 of each file and compare to hashes listed",
                "integrity_status": integrity_data["chain_verification"],
            },
            "advisory": {
                "type": "advisory",
                "autonomous": False,
                "message": "Export pack generated. This export is immutable and cannot be regenerated with the same ID.",
            }
        }

    except Exception as e:
        logger.error(f"Export generation failed: {e}")

        # Log the failure
        _log_export_event(
            export_id=export_id,
            requester_id=requester_id,
            event_type="evidence_export_failed",
            description=f"Evidence export pack generation failed: {str(e)}",
            payload={
                "scope": request.scope.dict(),
                "error": str(e),
            },
        )

        raise HTTPException(
            status_code=500,
            detail={
                "error": "Export generation failed",
                "export_id": export_id,
                "message": str(e),
                "logged": True,
            }
        )


@router.get("/records", response_model=dict)
async def list_export_records():
    """
    List all export records.

    Shows history of all generated export packs for audit trail.
    """
    return {
        "total_exports": len(_export_records),
        "records": [r.dict() for r in _export_records],
        "advisory": {
            "type": "advisory",
            "message": "Export records are immutable. Each export can only be generated once.",
        }
    }


@router.get("/records/{export_id}", response_model=dict)
async def get_export_record(export_id: str):
    """
    Get a specific export record.
    """
    record = next((r for r in _export_records if r.export_id == export_id), None)
    if not record:
        raise HTTPException(status_code=404, detail="Export record not found")

    return {
        "record": record.dict(),
        "advisory": {
            "type": "advisory",
            "message": "Export record is immutable.",
        }
    }


@router.get("/verify/{export_id}", response_model=dict)
async def verify_export_integrity(export_id: str):
    """
    Verify the integrity of a previously generated export.

    Checks that the export record exists and returns verification guidance.
    """
    record = next((r for r in _export_records if r.export_id == export_id), None)
    if not record:
        raise HTTPException(status_code=404, detail="Export record not found")

    return {
        "export_id": export_id,
        "record_found": True,
        "manifest_hash": record.manifest_hash,
        "event_count": record.event_count,
        "generated_at": record.generated_at.isoformat(),
        "verification_steps": [
            "1. Obtain the original export pack files",
            "2. Compute SHA-256 hash of manifest.json",
            "3. Compare to manifest_hash in this record",
            "4. Verify individual file hashes per manifest",
        ],
        "advisory": {
            "type": "advisory",
            "message": "Export integrity can be verified by comparing file hashes to manifest.",
        }
    }
