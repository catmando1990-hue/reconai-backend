from __future__ import annotations

import hashlib
from datetime import datetime
from uuid import uuid4
from fastapi import APIRouter, Depends, Response, Request, HTTPException
from reportlab.lib.pagesizes import LETTER
from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
import io

from app.auth_context import get_current_context
from app.audit import record_audit_event, AuditError

router = APIRouter()


@router.post("/govcon/export/dcaa/pdf")
async def export_for_dcaa_pdf(
    request: Request,
    ctx=Depends(get_current_context),
):
    """
    Export DCAA compliance PDF.

    AUDIT: FAIL-CLOSED - If audit fails, export is aborted.
    """
    # Generate or extract request_id for traceability
    request_id = request.headers.get("X-Request-ID") or str(uuid4())

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=LETTER)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("DCAA Export (Advisory / Read-only)", styles["Title"]),
        Paragraph("This document is generated on-demand and is advisory-only.", styles["Normal"]),
    ]
    doc.build(story)

    pdf_bytes = buf.getvalue()
    file_hash = hashlib.sha256(pdf_bytes).hexdigest()

    # AUDIT: FAIL-CLOSED - If this fails, the export is aborted
    try:
        await record_audit_event(
            actor={
                "user_id": ctx.get("user_id"),
                "email": ctx.get("email"),
                "org_id": ctx.get("org_id"),
                "tier": ctx.get("tier"),
            },
            action="govcon.export",
            resource_type="export",
            resource_id="dcaa_pdf",
            status="ok",
            metadata={
                "export": "dcaa",
                "format": "pdf",
                "hash": file_hash,
                "timestamp": datetime.utcnow().isoformat(),
            },
            request_id=request_id,
        )
    except AuditError as e:
        # FAIL-CLOSED: Audit failure aborts the request
        raise HTTPException(
            status_code=500,
            detail={
                "ok": False,
                "error": "AUDIT_FAILED",
                "message": "Export aborted: audit recording failed",
                "request_id": request_id,
            },
        ) from e

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="DCAA_Export.pdf"',
            "X-Request-ID": request_id,
        },
    )
