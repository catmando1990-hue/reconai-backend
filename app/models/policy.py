# app/models/policy.py
# Phase 70-72 — Policy snapshot models for enterprise features

from pydantic import BaseModel
from typing import Dict, List, Literal

FeatureFlagKey = Literal['enterprise_mode', 'policy_enforcement', 'white_label', 'evidence_mapping']
Role = Literal['user', 'admin', 'enterprise_admin']


class PolicySnapshot(BaseModel):
    flags: Dict[FeatureFlagKey, bool]
    roles: List[Role]
    updatedAtISO: str
