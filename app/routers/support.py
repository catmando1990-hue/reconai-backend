# app/routers/support.py
# Phase 75 — Enterprise SLA & Support Surfaces

from fastapi import APIRouter
from datetime import datetime, timezone

from app.models.support import SupportTicketCreate, SupportTicket

router = APIRouter(prefix='/support', tags=['support'])


@router.post('/tickets', response_model=SupportTicket)
async def create_support_ticket(payload: SupportTicketCreate):
    """
    Create a support ticket.

    Neutral wording only. No SLA claims.
    """
    return SupportTicket(
        id='tkt_1',
        createdAt=datetime.now(timezone.utc),
        status='open',
        subject=payload.subject,
        description=payload.description,
        priority=payload.priority,
        note='Request received. Response timelines depend on plan and availability.',
    )
