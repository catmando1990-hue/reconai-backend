from __future__ import annotations

import hashlib
from datetime import datetime
from fastapi import APIRouter, Response
from reportlab.lib.pagesizes import LETTER
from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
import io

from app.auth_context import get_current_context
from app.audit import record_audit_event

router = APIRouter()

@router.post("/govcon/export/dcaa/pdf")
def export_for_dcaa_pdf():
    ctx = get_current_context()

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

    record_audit_event(
        ctx=ctx,
        event_type="govcon.export",
        payload={
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
