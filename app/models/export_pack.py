# app/models/export_pack.py
# Phase 74 — Data Retention & Export Controls

from pydantic import BaseModel
from typing import List, Literal

ExportInclude = Literal['audit', 'evidence', 'policy']


class ExportPackRequest(BaseModel):
    rangeStartISO: str
    rangeEndISO: str
    include: List[ExportInclude]


class ExportPackResponse(BaseModel):
    requestId: str
    status: Literal['queued', 'processing', 'complete', 'failed']
