from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Dict, Optional, TypedDict

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from jwt import PyJWKClient

from app.db import DB_PATH
from app.errors import not_authenticated, org_required
from app.services.organization_service import OrganizationService


CLERK_JWKS_URL = os.getenv("CLERK_JWKS_URL", "https://api.clerk.com/v1/jwks")


class AuthContext(TypedDict):
    user_id: str
    email: str
    org_id: str
    tier: str
    features: list[str]


class AuthIdentity(TypedDict):
    user_id: str
    email: str
    default_org_id: Optional[str]


@lru_cache()
def _get_jwks_client() -> PyJWKClient:
    if not CLERK_JWKS_URL:
        raise ValueError("CLERK_JWKS_URL not configured")
    return PyJWKClient(CLERK_JWKS_URL)


def _parse_bearer_token(authorization: Optional[str]) -> str:
    if not authorization:
        not_authenticated("Missing authorization header")

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        not_authenticated("Invalid authorization header format. Expected: Bearer <token>")

    return parts[1]


def verify_clerk_token(token: str) -> Dict[str, Any]:
    if not token:
        not_authenticated("No authentication token provided")

    try:
        jwks_client = _get_jwks_client()
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            options={"verify_exp": True},
        )
        return payload
    except jwt.ExpiredSignatureError:
        not_authenticated("Token has expired")
    except jwt.InvalidTokenError as e:
        not_authenticated(f"Invalid token: {str(e)}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "AUTH_ERROR", "message": f"Token verification failed: {str(e)}"},
        )


def get_org_service() -> OrganizationService:
    return OrganizationService(DB_PATH)


def _resolve_org_id(service: OrganizationService, user_id: str, default_org_id: Optional[str]) -> str:
    if default_org_id:
        return default_org_id

    orgs = service.list_user_organizations(user_id)
    if orgs:
        return orgs[0].id

    org_required("No active organization")
    raise AssertionError("unreachable")


async def get_current_identity(
    authorization: Optional[str] = Header(None),
    service: OrganizationService = Depends(get_org_service),
) -> AuthIdentity:
    token = _parse_bearer_token(authorization)
    payload = verify_clerk_token(token)

    clerk_user_id = payload.get("sub")
    email = payload.get("email")

    if not clerk_user_id or not email:
        not_authenticated("Invalid token: missing required claims")

    user = service.get_user_by_email(email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "USER_NOT_FOUND", "message": "User not found. Please complete signup."},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "NOT_AUTHORIZED", "message": "User account is inactive"},
        )

    return {"user_id": user.id, "email": user.email, "default_org_id": user.default_org_id}


async def get_current_context(
    identity: AuthIdentity = Depends(get_current_identity),
    service: OrganizationService = Depends(get_org_service),
) -> AuthContext:
    org_id = _resolve_org_id(service, identity["user_id"], identity.get("default_org_id"))
    # Prefer looking up org via resolved org_id; if org lookup fails, fall back to defaults.
    org = service.get_organization(org_id)

    tier = org.tier.value if org and getattr(org, "tier", None) else "free"

    features: list[str] = []
    if org and getattr(org, "features", None):
        try:
            features = [k for k, v in org.features.model_dump().items() if v]
        except Exception:
            features = []

    return {
        "user_id": identity["user_id"],
        "email": identity["email"],
        "org_id": org_id,
        "tier": tier,
        "features": features,
    }


async def get_current_user_id(identity: AuthIdentity = Depends(get_current_identity)) -> str:
    return identity["user_id"]


async def get_current_organization_id(ctx: AuthContext = Depends(get_current_context)) -> str:
    return ctx["org_id"]


# Request-style helper (matches the patch suggestion), backed by middleware.
def get_current_user(request: Request) -> AuthContext:
    user = getattr(request.state, "user", None)
    if not user:
        not_authenticated("Authentication required")

    org_id = user.get("org_id")
    if not org_id:
        org_required("Active organization required")

    return {
        "user_id": user["user_id"],
        "email": user["email"],
        "org_id": org_id,
        "tier": user.get("tier", "free"),
        "features": user.get("features", []),
    }
