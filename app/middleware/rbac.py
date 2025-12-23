# app/middleware/rbac.py

"""
Role-Based Access Control (RBAC) Middleware
Enforces permissions based on user's role in organization
"""

from fastapi import HTTPException, status, Depends
from typing import Callable, Optional
from functools import wraps

from ..models_multitenancy import User, OrganizationMember, Permissions, UserRole
from ..services.organization_service import OrganizationService
from ..db import DB_PATH


class RBACMiddleware:
    """RBAC enforcement middleware"""

    def __init__(self):
        self.service = OrganizationService(DB_PATH)

    def get_user_permissions(
        self,
        user_id: str,
        org_id: str
    ) -> tuple[OrganizationMember, Permissions]:
        """
        Get user's membership and permissions for organization

        Returns:
            (member, permissions)

        Raises:
            HTTPException: If user is not a member or inactive
        """
        member = self.service.get_organization_member(org_id, user_id)

        if not member:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"You are not a member of organization {org_id}"
            )

        if not member.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your membership is inactive"
            )

        # Parse permissions from dict or Permissions object
        if isinstance(member.permissions, dict):
            permissions = Permissions(**member.permissions)
        else:
            permissions = member.permissions

        return member, permissions

    def check_permission(
        self,
        user_id: str,
        org_id: str,
        required_permission: str
    ) -> bool:
        """
        Check if user has specific permission in organization

        Args:
            user_id: User ID to check
            org_id: Organization ID
            required_permission: Permission name (e.g., 'create_transactions')

        Returns:
            True if user has permission

        Raises:
            HTTPException: If permission denied
        """
        member, permissions = self.get_user_permissions(user_id, org_id)

        # Check if permission exists and is True
        has_permission = getattr(permissions, required_permission, False)

        if not has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {required_permission} required"
            )

        return True

    def check_role(
        self,
        user_id: str,
        org_id: str,
        allowed_roles: list[UserRole]
    ) -> bool:
        """
        Check if user has one of the allowed roles

        Args:
            user_id: User ID to check
            org_id: Organization ID
            allowed_roles: List of allowed roles

        Returns:
            True if user has allowed role

        Raises:
            HTTPException: If role not allowed
        """
        member, _ = self.get_user_permissions(user_id, org_id)

        if member.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role {member.role.value} not authorized. Required: {[r.value for r in allowed_roles]}"
            )

        return True

    def check_feature(
        self,
        org_id: str,
        feature_name: str
    ) -> bool:
        """
        Check if organization has access to feature

        Args:
            org_id: Organization ID
            feature_name: Feature name (e.g., 'invoicing', 'multi_user')

        Returns:
            True if feature is enabled

        Raises:
            HTTPException: If feature not available
        """
        has_feature = self.service.check_feature(org_id, feature_name)

        if not has_feature:
            org = self.service.get_organization(org_id)
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Feature '{feature_name}' not available on {org.tier.value} plan. Please upgrade."
            )

        return True

    def check_limit(
        self,
        org_id: str,
        limit_name: str,
        current_count: int
    ) -> tuple[bool, int]:
        """
        Check if organization is within usage limit

        Args:
            org_id: Organization ID
            limit_name: Limit name (e.g., 'max_users', 'max_entities')
            current_count: Current usage count

        Returns:
            (within_limit, max_allowed)

        Raises:
            HTTPException: If limit exceeded
        """
        within_limit, max_allowed = self.service.check_limit(org_id, limit_name, current_count)

        if not within_limit:
            org = self.service.get_organization(org_id)
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Limit exceeded: {current_count}/{max_allowed} {limit_name}. Upgrade to {org.tier.value} plan or higher."
            )

        return within_limit, max_allowed


# Global RBAC instance
rbac = RBACMiddleware()


# =========================================================================
# DEPENDENCY FUNCTIONS FOR FASTAPI
# =========================================================================

def require_permission(permission: str):
    """
    Dependency factory: Require specific permission

    Usage:
        @router.post("/transactions")
        async def create_transaction(
            org_id: str,
            current_user_id: str = Depends(get_current_user_id),
            _: bool = Depends(require_permission("create_transactions"))
        ):
            ...
    """
    def check(org_id: str, current_user_id: str) -> bool:
        return rbac.check_permission(current_user_id, org_id, permission)
    return check


def require_role(*allowed_roles: UserRole):
    """
    Dependency factory: Require specific role(s)

    Usage:
        @router.delete("/organization")
        async def delete_org(
            org_id: str,
            current_user_id: str = Depends(get_current_user_id),
            _: bool = Depends(require_role(UserRole.OWNER))
        ):
            ...
    """
    def check(org_id: str, current_user_id: str) -> bool:
        return rbac.check_role(current_user_id, org_id, list(allowed_roles))
    return check


def require_feature(feature_name: str):
    """
    Dependency factory: Require organization has feature enabled

    Usage:
        @router.post("/invoices")
        async def create_invoice(
            org_id: str,
            _: bool = Depends(require_feature("invoicing"))
        ):
            ...
    """
    def check(org_id: str) -> bool:
        return rbac.check_feature(org_id, feature_name)
    return check


def check_usage_limit(limit_name: str, current_count: int):
    """
    Dependency factory: Check usage limit

    Usage:
        @router.post("/users")
        async def add_user(
            org_id: str,
            current_count: int,  # Calculate before calling
            _: tuple = Depends(check_usage_limit("max_users", current_count))
        ):
            ...
    """
    def check(org_id: str) -> tuple[bool, int]:
        return rbac.check_limit(org_id, limit_name, current_count)
    return check


# =========================================================================
# HELPER FUNCTIONS
# =========================================================================

def get_org_context(
    org_id: str,
    user_id: str
) -> dict:
    """
    Get organization context for current user

    Returns dict with:
    - organization: Organization object
    - member: OrganizationMember object
    - permissions: Permissions object
    - features: FeatureFlags object
    """
    service = OrganizationService(DB_PATH)

    org = service.get_organization(org_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organization {org_id} not found"
        )

    member = service.get_organization_member(org_id, user_id)
    if not member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this organization"
        )

    permissions = Permissions(**member.permissions) if isinstance(member.permissions, dict) else member.permissions

    return {
        "organization": org,
        "member": member,
        "permissions": permissions,
        "features": org.features
    }


def require_org_access(org_id: str, user_id: str) -> bool:
    """
    Simple check: Is user a member of organization?

    Raises HTTPException if not
    """
    service = OrganizationService(DB_PATH)
    member = service.get_organization_member(org_id, user_id)

    if not member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this organization"
        )

    if not member.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your membership is inactive"
        )

    return True
