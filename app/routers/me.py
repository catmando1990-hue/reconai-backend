# app/routers/me.py

"""Current user + organization context.

Build 1 contract: GET /api/me returns { user, org, permissions, request_id }.

- Auth is derived from Clerk JWT (Authorization: Bearer <token>)
- Organization is derived from server-side context (never trusted from client input)
- Auto-provisions personal workspace for new users (never 404s)
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, Field

from app.auth_context import AuthContext, get_current_context
from app.db import DB_PATH
from app.models_multitenancy import Organization, User
from app.services.organization_service import OrganizationService


router = APIRouter(prefix="/api", tags=["Me"])


class MeUser(BaseModel):
    id: str
    email: EmailStr
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    avatar_url: Optional[str] = None
    default_org_id: Optional[str] = None
    is_active: bool
    email_verified: bool


class MeOrg(BaseModel):
    id: str
    name: str
    slug: str
    tier: str
    subscription_status: Optional[str] = None
    features: List[str] = Field(default_factory=list)
    is_personal_workspace: bool = False


class MePermissions(BaseModel):
    role: str
    permissions: Dict[str, Any] = Field(default_factory=dict)


class MeResponse(BaseModel):
    request_id: str
    user: MeUser
    org: MeOrg
    permissions: MePermissions


def get_org_service() -> OrganizationService:
    return OrganizationService(DB_PATH)


def _to_user(u: User) -> MeUser:
    return MeUser(
        id=u.id,
        email=u.email,
        first_name=u.first_name,
        last_name=u.last_name,
        avatar_url=u.avatar_url,
        default_org_id=u.default_org_id,
        is_active=bool(u.is_active),
        email_verified=bool(u.email_verified),
    )


def _to_org(o: Organization, features: List[str]) -> MeOrg:
    # Detect personal workspace by org ID prefix or slug prefix
    is_personal = o.id.startswith("org-personal-") or o.slug.startswith("personal-")
    return MeOrg(
        id=o.id,
        name=o.name,
        slug=o.slug,
        tier=o.tier.value,
        subscription_status=o.subscription_status,
        features=features,
        is_personal_workspace=is_personal,
    )


@router.get("/me", response_model=MeResponse)
async def me(
    ctx: AuthContext = Depends(get_current_context),
    service: OrganizationService = Depends(get_org_service),
):
    """
    Return authenticated user + active organization + effective permissions.

    Auto-provisions personal workspace for new Clerk users.
    Never returns 404 for valid authenticated users.

    Response includes request_id for tracing.
    """
    request_id = str(uuid.uuid4())

    user = service.get_user(ctx["user_id"])
    org = service.get_organization(ctx["org_id"])

    # These should exist if auth_context resolved them, but keep response resilient.
    if user is None:
        # Let FastAPI raise a 500 instead of leaking auth logic; this indicates DB drift.
        raise RuntimeError("Authenticated user not found")
    if org is None:
        raise RuntimeError("Active organization not found")

    member = service.get_organization_member(org.id, user.id)
    role = member.role.value if member else "owner"  # Default to owner for personal workspace
    perms = member.permissions if member and member.permissions else {}

    return MeResponse(
        request_id=request_id,
        user=_to_user(user),
        org=_to_org(org, ctx.get("features", [])),
        permissions=MePermissions(role=role, permissions=perms),
    )
