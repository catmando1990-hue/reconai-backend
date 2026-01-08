# app/models/rbac.py
# Phase 73 — Enterprise RBAC Expansion

from pydantic import BaseModel
from typing import List, Literal

Permission = Literal[
    'audit.read',
    'policy.read',
    'policy.write',
    'evidence.read',
    'retention.read',
    'retention.write',
    'export.request',
    'support.create',
    'status.read',
]


class RbacSnapshot(BaseModel):
    roles: List[str]
    permissions: List[Permission]
    updatedAtISO: str
