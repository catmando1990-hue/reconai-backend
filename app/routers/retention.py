# app/routers/retention.py
# Phase 74 — Data Retention & Export Controls

from fastapi import APIRouter
from datetime import datetime, timezone

from app.models.retention import RetentionPolicy

router = APIRouter(prefix='/retention', tags=['retention'])


@router.get('/policy', response_model=RetentionPolicy)
async def get_retention_policy():
    """
    Get current data retention policy.

    Wiring placeholder. Replace with tenant-aware retention policy store.
    """
    return RetentionPolicy(
        scope='audit',
        days=365,
        updatedAt=datetime.now(timezone.utc)
    )
