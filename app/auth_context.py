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


class MemberPermissions(TypedDict):
    role: str
    can_view: bool
    can_edit: bool
    can_delete: bool
    can_manage_users: bool
    can_manage_billing: bool


class AuthContext(TypedDict):
    user_id: str
    email: str
    org_id: str
    tier: str
    features: list[str]
    permissions: Optional[MemberPermissions]
    clerk_metadata: Optional[Dict[str, Any]]  # Clerk publicMetadata from JWT


class AuthIdentity(TypedDict):
    user_id: str
    email: str
    default_org_id: Optional[str]
    clerk_metadata: Optional[Dict[str, Any]]  # Clerk publicMetadata from JWT


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


def _lookup_user_by_clerk_id(service: OrganizationService, clerk_user_id: str):
    """Look up user by Clerk user ID (sub claim)"""
    # First try to find by clerk_user_id field if it exists
    try:
        user = service.get_user_by_clerk_id(clerk_user_id)
        if user:
            return user
    except Exception as e:
        import logging
        logging.warning(f"Clerk ID lookup failed for {clerk_user_id}: {e}")
    return None


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
    """
    Resolve authenticated user identity from Clerk JWT.

    Auto-provisions personal workspace for new users (never 404s for valid Clerk tokens).
    """
    import logging
    logger = logging.getLogger(__name__)

    token = _parse_bearer_token(authorization)
    payload = verify_clerk_token(token)

    clerk_user_id = payload.get("sub")
    email = payload.get("email")

    if not clerk_user_id:
        not_authenticated("Invalid token: missing sub claim")

    # Try to find user by email first (if present in token)
    user = None
    if email:
        user = service.get_user_by_email(email)

    # If no email in token or user not found by email, try by Clerk ID
    if not user:
        user = _lookup_user_by_clerk_id(service, clerk_user_id)

    # AUTO-PROVISION: If user not found, create personal workspace
    if not user:
        if not email:
            # Cannot auto-provision without email
            logger.warning(f"Cannot auto-provision user without email: clerk_id={clerk_user_id}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "EMAIL_REQUIRED",
                    "message": "Email is required for account creation. Please update your Clerk profile.",
                    "clerk_user_id": clerk_user_id,
                },
            )

        logger.info(f"Auto-provisioning new user: clerk_id={clerk_user_id}, email={email}")

        # Extract name from Clerk metadata if available
        first_name = payload.get("given_name") or payload.get("first_name")
        last_name = payload.get("family_name") or payload.get("last_name")

        try:
            user, _org = service.auto_provision_personal_user(
                clerk_user_id=clerk_user_id,
                email=email,
                first_name=first_name,
                last_name=last_name,
            )
            logger.info(f"Auto-provisioned user {user.id} for clerk_id={clerk_user_id}")
        except Exception as e:
            logger.error(f"Auto-provision failed for {clerk_user_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "error": "PROVISION_FAILED",
                    "message": "Failed to create user account. Please try again.",
                },
            )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "NOT_AUTHORIZED", "message": "User account is inactive"},
        )

    # Extract Clerk metadata from JWT (set via Clerk session token customization)
    clerk_metadata = payload.get("metadata")

    return {"user_id": user.id, "email": user.email, "default_org_id": user.default_org_id, "clerk_metadata": clerk_metadata}


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

    # Get user's role/permissions in the organization
    permissions: Optional[MemberPermissions] = None
    try:
        member = service.get_organization_member(org_id, identity["user_id"])
        if member:
            permissions = {
                "role": member.role.value if hasattr(member.role, 'value') else str(member.role),
                "can_view": member.permissions.can_view if member.permissions else True,
                "can_edit": member.permissions.can_edit if member.permissions else False,
                "can_delete": member.permissions.can_delete if member.permissions else False,
                "can_manage_users": member.permissions.can_manage_users if member.permissions else False,
                "can_manage_billing": member.permissions.can_manage_billing if member.permissions else False,
            }
    except Exception:
        # If we can't get member info, default to owner permissions for the org owner
        if org and hasattr(org, 'owner_id') and org.owner_id == identity["user_id"]:
            permissions = {
                "role": "owner",
                "can_view": True,
                "can_edit": True,
                "can_delete": True,
                "can_manage_users": True,
                "can_manage_billing": True,
            }

    return {
        "user_id": identity["user_id"],
        "email": identity["email"],
        "org_id": org_id,
        "tier": tier,
        "features": features,
        "permissions": permissions,
        "clerk_metadata": identity.get("clerk_metadata"),
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
