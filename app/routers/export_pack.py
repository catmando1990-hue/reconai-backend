# app/routers/export_pack.py
# Phase 74 — Data Retention & Export Controls

from fastapi import APIRouter

from app.models.export_pack import ExportPackRequest, ExportPackResponse

router = APIRouter(prefix='/exports', tags=['exports'])


@router.post('/request', response_model=ExportPackResponse)
async def request_export_pack(payload: ExportPackRequest):
    """
    Request an export pack for audit/evidence/policy data.

    Server-side generation stub. Replace with async job + signed URL store.
    """
    return ExportPackResponse(
        requestId='exp_1',
        status='queued'
    )
