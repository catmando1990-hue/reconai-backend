# app/models/retention.py
# Phase 74 — Data Retention & Export Controls

from pydantic import BaseModel
from typing import Literal
from datetime import datetime

RetentionScope = Literal['audit', 'evidence', 'exports']


class RetentionPolicy(BaseModel):
    scope: RetentionScope
    days: int
    updatedAt: datetime
