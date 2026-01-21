# app/routers/profile_complete.py
"""
Profile Completion API - P0 Onboarding Unblock

This endpoint handles the atomic profile completion operation that
guarantees users can progress past the onboarding flow.

CANONICAL LAWS:
- Idempotent: Safe to call multiple times
- Atomic: All operations succeed or fail together
- Fail-closed: Returns explicit error states
- Auth-required: Uses get_current_context

WHY THIS EXISTS:
Users were stuck on "Complete your profile" after MFA enrollment
because there was no endpoint to:
1) Persist first_name/last_name
2) Create org if missing
3) Mark profile as complete
4) Return canonical success response
"""

from __future__ import annotations

import sqlite3
import logging
from uuid import uuid4
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth_context import get_current_context, get_current_identity, AuthContext, AuthIdentity
from app.db import DB_PATH
from app.services.organization_service import OrganizationService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/profile", tags=["Profile"])


def get_org_service() -> OrganizationService:
    return OrganizationService(DB_PATH)


class ProfileCompleteRequest(BaseModel):
    """Request to complete user profile during onboarding."""
    first_name: str
    last_name: str


class ProfileCompleteResponse(BaseModel):
    """Canonical response for profile completion."""
    ok: bool
    profileCompleted: bool
    orgId: Optional[str] = None
    userId: Optional[str] = None
    message: Optional[str] = None
    request_id: str


@router.post("/complete", response_model=ProfileCompleteResponse)
async def complete_profile(
    payload: ProfileCompleteRequest,
    identity: AuthIdentity = Depends(get_current_identity),
    service: OrganizationService = Depends(get_org_service),
):
    """
    Complete user profile during onboarding.

    This is an ATOMIC, IDEMPOTENT operation that:
    1) Persists first_name and last_name
    2) Creates organization if missing
    3) Links user to organization
    4) Sets profile_completed = true
    5) Returns canonical success response

    Safe to call multiple times - will return success if already complete.

    Response Contract:
    {
        "ok": true,
        "profileCompleted": true,
        "orgId": "<organization_id>",
        "userId": "<user_id>",
        "request_id": "<uuid>"
    }
    """
    request_id = str(uuid4())
    user_id = identity["user_id"]
    email = identity["email"]

    logger.info(f"[{request_id}] Profile completion requested for user {user_id}")

    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row

            # 1) Get current user state
            cursor = conn.execute(
                "SELECT id, first_name, last_name, default_org_id, profile_completed FROM users WHERE id = ?",
                (user_id,)
            )
            user_row = cursor.fetchone()

            if not user_row:
                logger.error(f"[{request_id}] User not found: {user_id}")
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "error": "USER_NOT_FOUND",
                        "message": "User account not found. Please sign in again.",
                        "request_id": request_id,
                    }
                )

            current_org_id = user_row["default_org_id"]
            already_complete = bool(user_row["profile_completed"])

            # 2) Check if user already has an org
            org_id = current_org_id
            if not org_id:
                # Check if user has any organizations
                cursor = conn.execute(
                    "SELECT organization_id FROM organization_members WHERE user_id = ? LIMIT 1",
                    (user_id,)
                )
                member_row = cursor.fetchone()
                if member_row:
                    org_id = member_row["organization_id"]

            # 3) Create organization if still missing
            if not org_id:
                logger.info(f"[{request_id}] Creating organization for user {user_id}")

                # Generate org slug from email
                slug_base = email.split("@")[0].lower()
                slug_base = "".join(c if c.isalnum() or c == "-" else "-" for c in slug_base)
                org_slug = f"personal-{slug_base}"
                org_name = f"{payload.first_name}'s Workspace"
                org_id = f"org-personal-{user_id}"

                # Check if slug exists and make unique if needed
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM organizations WHERE slug = ?",
                    (org_slug,)
                )
                if cursor.fetchone()[0] > 0:
                    org_slug = f"{org_slug}-{uuid4().hex[:6]}"

                # Create organization
                now = datetime.utcnow().isoformat()
                conn.execute("""
                    INSERT INTO organizations (id, name, slug, tier, owner_id, created_at, updated_at)
                    VALUES (?, ?, ?, 'free', ?, ?, ?)
                """, (org_id, org_name, org_slug, user_id, now, now))

                # Create organization member record
                member_id = f"member-{uuid4().hex[:12]}"
                conn.execute("""
                    INSERT INTO organization_members (id, organization_id, user_id, role, created_at)
                    VALUES (?, ?, ?, 'owner', ?)
                """, (member_id, org_id, user_id, now))

                logger.info(f"[{request_id}] Created organization {org_id} for user {user_id}")

            # 4) Update user profile
            conn.execute("""
                UPDATE users
                SET first_name = ?,
                    last_name = ?,
                    default_org_id = ?,
                    profile_completed = 1,
                    updated_at = datetime('now')
                WHERE id = ?
            """, (payload.first_name, payload.last_name, org_id, user_id))

            conn.commit()

            logger.info(f"[{request_id}] Profile completed for user {user_id}, org {org_id}")

            return ProfileCompleteResponse(
                ok=True,
                profileCompleted=True,
                orgId=org_id,
                userId=user_id,
                message="Profile completed successfully" if not already_complete else "Profile already complete",
                request_id=request_id,
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[{request_id}] Profile completion failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "PROFILE_COMPLETION_FAILED",
                "message": "Failed to complete profile. Please try again.",
                "request_id": request_id,
            }
        )


@router.get("/status")
async def get_profile_status(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Get current profile completion status.

    Returns whether the user has completed their profile setup.
    """
    request_id = str(uuid4())
    user_id = ctx["user_id"]
    org_id = ctx["org_id"]

    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.execute(
                "SELECT first_name, last_name, profile_completed FROM users WHERE id = ?",
                (user_id,)
            )
            row = cursor.fetchone()

            if not row:
                return {
                    "ok": True,
                    "profileCompleted": False,
                    "hasName": False,
                    "hasOrg": bool(org_id),
                    "orgId": org_id,
                    "request_id": request_id,
                }

            first_name, last_name, profile_completed = row
            has_name = bool(first_name and last_name)

            return {
                "ok": True,
                "profileCompleted": bool(profile_completed),
                "hasName": has_name,
                "hasOrg": bool(org_id),
                "orgId": org_id,
                "firstName": first_name,
                "lastName": last_name,
                "request_id": request_id,
            }

    except Exception as e:
        logger.error(f"[{request_id}] Profile status check failed: {e}", exc_info=True)
        return {
            "ok": False,
            "profileCompleted": False,
            "error": "STATUS_CHECK_FAILED",
            "request_id": request_id,
        }
