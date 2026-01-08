# app/models/support.py
# Phase 75 — Enterprise SLA & Support Surfaces

from pydantic import BaseModel
from typing import Optional, Literal
from datetime import datetime

SupportPriority = Literal['low', 'medium', 'high']
SupportStatus = Literal['open', 'triaged', 'closed']


class SupportTicketCreate(BaseModel):
    subject: str
    description: str
    priority: SupportPriority = 'low'


class SupportTicket(BaseModel):
    id: str
    createdAt: datetime
    status: SupportStatus
    subject: str
    description: str
    priority: SupportPriority
    note: Optional[str] = None
