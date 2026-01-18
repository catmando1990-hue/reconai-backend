from __future__ import annotations

import csv
import io
import hashlib
from datetime import datetime, timezone
from fastapi import APIRouter, Response

from app.auth_context import get_current_context
from app.services.audit_store import AuditEventInput, insert_audit_event

router = APIRouter()

@router.post("/govcon/export/dcaa")
def export_for_dcaa():
    """
    Export DCAA-compliant audit data as CSV.

    Canonical: manual-run, read-only (except audit log), advisory-only.
    User must click to trigger. No automatic exports.
    """
    ctx = get_current_context()

    # Demo data - replace with real query when ready
    rows = [
        {"category": "Labor", "amount": 0},
        {"category": "Indirect", "amount": 0},
        {"category": "ODC", "amount": 0},
    ]

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["category", "amount"])
    writer.writeheader()
    for r in rows:
        writer.writerow(r)

    csv_bytes = buf.getvalue().encode("utf-8")
    file_hash = hashlib.sha256(csv_bytes).hexdigest()

    # Record audit event for DCAA compliance (append-only, hash-chained)
    insert_audit_event(
        AuditEventInput(
            actor_id=ctx["user_id"],
            event_type="govcon.export.dcaa",
            entity_type="export",
            entity_id=file_hash[:16],  # Use truncated hash as entity ID
            payload={
                "export_type": "dcaa",
                "format": "csv",
                "file_hash": file_hash,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "org_id": ctx["org_id"],
            },
        )
    )

    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="DCAA_Export.csv"'
        },
    )
