# app/models/enterprise_roles.py
# Phase 70-72 — Enterprise role helpers

from typing import Literal, Sequence

Role = Literal['user', 'admin', 'enterprise_admin']


def has_any_role(user_roles: Sequence[Role], required: Sequence[Role]) -> bool:
    """Check if user has any of the required roles."""
    required_set = set(required)
    return any(r in required_set for r in user_roles)
