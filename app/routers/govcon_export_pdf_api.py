from __future__ import annotations

import hashlib
from datetime import datetime
from fastapi import APIRouter, Depends, Response
from reportlab.lib.pagesizes import LETTER
from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
import io

from app.auth_context import get_current_context
from app.audit import record_audit_event

router = APIRouter()

@router.post("/govcon/export/dcaa/pdf")
async def export_for_dcaa_pdf(ctx = Depends(get_current_context)):

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

    # Audit: best-effort, never blocks the request.
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
    )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="DCAA_Export.pdf"'},
    )
