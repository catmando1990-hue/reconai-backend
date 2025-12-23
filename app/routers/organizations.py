# app/routers/organizations.py

"""
Organization Management API
Multi-tenancy core endpoints for organization CRUD and member management
"""

from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime

from ..services.organization_service import OrganizationService
from ..models_multitenancy import (
    Organization, User, OrganizationMember,
    SubscriptionTier, UserRole, Industry,
    FeatureFlags, Permissions
)
from ..db import DB_PATH

router = APIRouter(prefix="/api/organizations", tags=["Organizations"])

# =========================================================================
# REQUEST/RESPONSE MODELS
# =========================================================================

class CreateOrganizationRequest(BaseModel):
    """Request to create new organization (signup flow)"""
    name: str = Field(..., min_length=1, max_length=100, description="Organization name")
    slug: str = Field(..., min_length=3, max_length=50, pattern="^[a-z0-9-]+$", description="URL-friendly slug")
    owner_email: EmailStr = Field(..., description="Owner's email address")
    tier: SubscriptionTier = Field(default=SubscriptionTier.INDIVIDUAL, description="Subscription tier")
    industry: Optional[Industry] = Field(None, description="Industry vertical")

class UpdateOrganizationRequest(BaseModel):
    """Request to update organization"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    industry: Optional[Industry] = None
    tier: Optional[SubscriptionTier] = None

class AddMemberRequest(BaseModel):
    """Request to add member to organization"""
    user_id: str = Field(..., description="User ID to add")
    role: UserRole = Field(default=UserRole.VIEWER, description="Role to assign")

class UpdateMemberRequest(BaseModel):
    """Request to update member role"""
    role: UserRole = Field(..., description="New role")

class OrganizationResponse(BaseModel):
    """Organization response"""
    id: str
    name: str
    slug: str
    tier: SubscriptionTier
    industry: Optional[Industry]
    subscription_status: str
    trial_ends_at: Optional[datetime]
    subscription_ends_at: Optional[datetime]
    features: FeatureFlags
    owner_user_id: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class MemberResponse(BaseModel):
    """Organization member response"""
    id: str
    organization_id: str
    user_id: str
    role: UserRole
    permissions: dict
    invited_at: Optional[datetime]
    joined_at: datetime
    is_active: bool
    user: dict  # User details

    class Config:
        from_attributes = True

class CreateOrganizationResponse(BaseModel):
    """Response after creating organization"""
    organization: OrganizationResponse
    user: dict
    message: str

# =========================================================================
# DEPENDENCY INJECTION
# =========================================================================

def get_org_service() -> OrganizationService:
    """Dependency: Get organization service instance"""
    return OrganizationService(DB_PATH)

# Import authentication dependencies from auth router
from .auth import get_current_user_id

# =========================================================================
# ORGANIZATION ENDPOINTS
# =========================================================================

@router.post("/", response_model=CreateOrganizationResponse, status_code=status.HTTP_201_CREATED)
async def create_organization(
    request: CreateOrganizationRequest,
    service: OrganizationService = Depends(get_org_service)
):
    """
    Create new organization (signup flow)

    This creates:
    - Organization with specified tier
    - Owner user account
    - Organization membership with owner role
    - Default entity
    - 14-day trial period
    """
    try:
        # Check if slug is available
        existing = service.get_organization_by_slug(request.slug)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Organization slug '{request.slug}' is already taken"
            )

        # Check if user email exists
        existing_user = service.get_user_by_email(request.owner_email)
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"User with email '{request.owner_email}' already exists"
            )

        # Create organization
        org, user = service.create_organization(
            name=request.name,
            slug=request.slug,
            owner_email=request.owner_email,
            tier=request.tier,
            industry=request.industry.value if request.industry else None
        )

        return CreateOrganizationResponse(
            organization=OrganizationResponse(**org.model_dump()),
            user={
                "id": user.id,
                "email": user.email,
                "default_org_id": user.default_org_id,
                "is_active": user.is_active,
                "email_verified": user.email_verified,
                "created_at": user.created_at
            },
            message=f"Organization '{org.name}' created successfully with 14-day trial"
        )

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/", response_model=List[OrganizationResponse])
async def list_user_organizations(
    current_user_id: str = Depends(get_current_user_id),
    service: OrganizationService = Depends(get_org_service)
):
    """
    List all organizations the current user belongs to

    Returns organizations ordered by most recently joined
    """
    try:
        orgs = service.list_user_organizations(current_user_id)
        return [OrganizationResponse(**org.model_dump()) for org in orgs]
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/{org_id}", response_model=OrganizationResponse)
async def get_organization(
    org_id: str,
    current_user_id: str = Depends(get_current_user_id),
    service: OrganizationService = Depends(get_org_service)
):
    """
    Get organization details

    User must be a member of the organization
    """
    try:
        # Check if user is member
        member = service.get_organization_member(org_id, current_user_id)
        if not member:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not a member of this organization"
            )

        org = service.get_organization(org_id)
        if not org:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Organization {org_id} not found"
            )

        return OrganizationResponse(**org.model_dump())

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.patch("/{org_id}", response_model=OrganizationResponse)
async def update_organization(
    org_id: str,
    request: UpdateOrganizationRequest,
    current_user_id: str = Depends(get_current_user_id),
    service: OrganizationService = Depends(get_org_service)
):
    """
    Update organization details

    Requires: Owner or Admin role
    """
    try:
        # Check permissions
        member = service.get_organization_member(org_id, current_user_id)
        if not member:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not a member of this organization"
            )

        if member.role not in [UserRole.OWNER, UserRole.ADMIN]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only owners and admins can update organization details"
            )

        # Build updates dict
        updates = {}
        if request.name is not None:
            updates['name'] = request.name
        if request.industry is not None:
            updates['industry'] = request.industry.value
        if request.tier is not None:
            # Only owner can change tier
            if member.role != UserRole.OWNER:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only owner can change subscription tier"
                )
            updates['tier'] = request.tier.value

        if not updates:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No valid fields to update"
            )

        org = service.update_organization(org_id, updates)
        if not org:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Organization {org_id} not found"
            )

        return OrganizationResponse(**org.model_dump())

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# =========================================================================
# MEMBER MANAGEMENT ENDPOINTS
# =========================================================================

@router.post("/{org_id}/members", response_model=MemberResponse, status_code=status.HTTP_201_CREATED)
async def add_organization_member(
    org_id: str,
    request: AddMemberRequest,
    current_user_id: str = Depends(get_current_user_id),
    service: OrganizationService = Depends(get_org_service)
):
    """
    Add member to organization (invite)

    Requires: Owner or Admin role with manage_users permission
    """
    try:
        # Check permissions
        member = service.get_organization_member(org_id, current_user_id)
        if not member:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not a member of this organization"
            )

        permissions = Permissions(**member.permissions) if isinstance(member.permissions, dict) else member.permissions
        if not permissions.manage_users:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to manage users"
            )

        # Check if user exists
        user = service.get_user(request.user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User {request.user_id} not found"
            )

        # Check if already a member
        existing_member = service.get_organization_member(org_id, request.user_id)
        if existing_member:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"User is already a member of this organization"
            )

        # Check user limit for tier
        org = service.get_organization(org_id)
        if not org:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Organization {org_id} not found"
            )

        members = service.list_organization_members(org_id)
        current_count = len(members)
        within_limit, max_allowed = service.check_limit(org_id, "max_users", current_count + 1)

        if not within_limit:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"User limit reached ({max_allowed} users). Upgrade your plan to add more users."
            )

        # Add member
        new_member = service.add_organization_member(
            org_id=org_id,
            user_id=request.user_id,
            role=request.role,
            invited_by=current_user_id
        )

        return MemberResponse(
            **new_member.model_dump(),
            user={
                "id": user.id,
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/{org_id}/members", response_model=List[MemberResponse])
async def list_organization_members(
    org_id: str,
    current_user_id: str = Depends(get_current_user_id),
    service: OrganizationService = Depends(get_org_service)
):
    """
    List all members of organization

    User must be a member of the organization
    """
    try:
        # Check if user is member
        member = service.get_organization_member(org_id, current_user_id)
        if not member:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not a member of this organization"
            )

        members = service.list_organization_members(org_id)

        return [
            MemberResponse(
                **m.model_dump(),
                user={
                    "id": u.id,
                    "email": u.email,
                    "first_name": u.first_name,
                    "last_name": u.last_name,
                    "avatar_url": u.avatar_url
                }
            )
            for m, u in members
        ]

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.patch("/{org_id}/members/{user_id}", response_model=MemberResponse)
async def update_organization_member(
    org_id: str,
    user_id: str,
    request: UpdateMemberRequest,
    current_user_id: str = Depends(get_current_user_id),
    service: OrganizationService = Depends(get_org_service)
):
    """
    Update member role

    Requires: Owner or Admin role with manage_users permission
    Cannot change owner role
    """
    try:
        # Check permissions
        current_member = service.get_organization_member(org_id, current_user_id)
        if not current_member:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not a member of this organization"
            )

        permissions = Permissions(**current_member.permissions) if isinstance(current_member.permissions, dict) else current_member.permissions
        if not permissions.manage_users:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to manage users"
            )

        # Get target member
        target_member = service.get_organization_member(org_id, user_id)
        if not target_member:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Member not found"
            )

        # Cannot change owner role
        if target_member.role == UserRole.OWNER:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot change owner role"
            )

        # Only owner can assign owner role
        if request.role == UserRole.OWNER and current_member.role != UserRole.OWNER:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only owner can assign owner role"
            )

        # Update role via service
        # For now, we'll need to add update_organization_member to service
        # Placeholder: directly update in database
        from ..models_multitenancy import ROLE_PERMISSIONS
        import sqlite3
        import json

        new_permissions = ROLE_PERMISSIONS[request.role]

        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                UPDATE organization_members
                SET role = ?, permissions = ?
                WHERE organization_id = ? AND user_id = ?
            """, (request.role.value, json.dumps(new_permissions.model_dump()), org_id, user_id))
            conn.commit()

        # Fetch updated member
        updated_member = service.get_organization_member(org_id, user_id)
        user = service.get_user(user_id)

        return MemberResponse(
            **updated_member.model_dump(),
            user={
                "id": user.id,
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.delete("/{org_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_organization_member(
    org_id: str,
    user_id: str,
    current_user_id: str = Depends(get_current_user_id),
    service: OrganizationService = Depends(get_org_service)
):
    """
    Remove member from organization

    Requires: Owner or Admin role with manage_users permission
    Cannot remove owner
    """
    try:
        # Check permissions
        current_member = service.get_organization_member(org_id, current_user_id)
        if not current_member:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not a member of this organization"
            )

        permissions = Permissions(**current_member.permissions) if isinstance(current_member.permissions, dict) else current_member.permissions
        if not permissions.manage_users:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to manage users"
            )

        # Get target member
        target_member = service.get_organization_member(org_id, user_id)
        if not target_member:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Member not found"
            )

        # Cannot remove owner
        if target_member.role == UserRole.OWNER:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot remove owner from organization"
            )

        # Soft delete (set is_active = 0)
        import sqlite3
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                UPDATE organization_members
                SET is_active = 0
                WHERE organization_id = ? AND user_id = ?
            """, (org_id, user_id))
            conn.commit()

        return None

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# =========================================================================
# FEATURE FLAG ENDPOINTS
# =========================================================================

@router.get("/{org_id}/features", response_model=dict)
async def get_organization_features(
    org_id: str,
    current_user_id: str = Depends(get_current_user_id),
    service: OrganizationService = Depends(get_org_service)
):
    """
    Get organization feature flags

    User must be a member of the organization
    """
    try:
        # Check if user is member
        member = service.get_organization_member(org_id, current_user_id)
        if not member:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not a member of this organization"
            )

        org = service.get_organization(org_id)
        if not org:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Organization {org_id} not found"
            )

        return {
            "organization_id": org.id,
            "tier": org.tier.value,
            "features": org.features.model_dump()
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/{org_id}/features/{feature_name}", response_model=dict)
async def check_organization_feature(
    org_id: str,
    feature_name: str,
    current_user_id: str = Depends(get_current_user_id),
    service: OrganizationService = Depends(get_org_service)
):
    """
    Check if organization has access to specific feature

    User must be a member of the organization
    """
    try:
        # Check if user is member
        member = service.get_organization_member(org_id, current_user_id)
        if not member:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not a member of this organization"
            )

        has_feature = service.check_feature(org_id, feature_name)

        return {
            "organization_id": org_id,
            "feature": feature_name,
            "enabled": has_feature
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
