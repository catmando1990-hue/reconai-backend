# app/routers/entities.py

"""
Entity Management API
Handles multi-entity support within organizations
"""

from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

from ..services.organization_service import OrganizationService
from ..models_multitenancy import Entity, EntityType
# from ..middleware import require_permission, require_feature, get_org_context  # TODO: Implement these
from ..db import DB_PATH
from app.auth_context import get_current_organization_id, get_current_user_id

router = APIRouter(prefix="/api/entities", tags=["Entities"])

# =========================================================================
# REQUEST/RESPONSE MODELS
# =========================================================================

class CreateEntityRequest(BaseModel):
    """Request to create new entity"""
    name: str = Field(..., min_length=1, max_length=100, description="Entity name")
    legal_name: str = Field(..., min_length=1, max_length=200, description="Legal business name")
    ein: Optional[str] = Field(None, pattern=r"^\d{2}-\d{7}$", description="EIN (XX-XXXXXXX)")
    entity_type: Optional[EntityType] = Field(None, description="Legal entity type")
    industry: Optional[str] = Field(None, description="Industry")
    address_line1: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = Field(None, pattern=r"^[A-Z]{2}$", description="Two-letter state code")
    zip: Optional[str] = Field(None, pattern=r"^\d{5}(-\d{4})?$", description="ZIP code")
    country: str = Field(default="US", description="Country code")
    default_currency: str = Field(default="USD", description="Default currency code")

class UpdateEntityRequest(BaseModel):
    """Request to update entity"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    legal_name: Optional[str] = Field(None, min_length=1, max_length=200)
    ein: Optional[str] = Field(None, pattern=r"^\d{2}-\d{7}$")
    entity_type: Optional[EntityType] = None
    industry: Optional[str] = None
    address_line1: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = Field(None, pattern=r"^[A-Z]{2}$")
    zip: Optional[str] = Field(None, pattern=r"^\d{5}(-\d{4})?$")
    country: Optional[str] = None
    default_currency: Optional[str] = None

class EntityResponse(BaseModel):
    """Entity response"""
    id: str
    organization_id: str
    name: str
    legal_name: Optional[str]
    ein: Optional[str]
    entity_type: Optional[EntityType]
    industry: Optional[str]
    address_line1: Optional[str]
    city: Optional[str]
    state: Optional[str]
    zip: Optional[str]
    country: Optional[str]
    default_currency: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True

# =========================================================================
# DEPENDENCY INJECTION
# =========================================================================

def get_service() -> OrganizationService:
    """Get organization service instance"""
    return OrganizationService(DB_PATH)

# =========================================================================
# ENTITY ENDPOINTS
# =========================================================================

@router.post("/", response_model=EntityResponse, status_code=status.HTTP_201_CREATED)
async def create_entity(
    request: CreateEntityRequest,
    org_id: str = Depends(get_current_organization_id),
    current_user_id: str = Depends(get_current_user_id),
    service: OrganizationService = Depends(get_service)
):
    """
    Create new entity within organization

    Requires:
    - multi_entity feature enabled (Professional tier+)
    - Owner role
    - Within max_entities limit
    """
    try:
        # Check feature access
        org = service.get_organization(org_id)
        if not org:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Organization {org_id} not found"
            )

        # Check multi_entity feature (Professional tier and above)
        if not org.features.multi_entity:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Multi-entity support requires Professional tier or higher. Current tier: {org.tier.value}"
            )

        # Check permissions - only Owner can create entities
        member = service.get_organization_member(org_id, current_user_id)
        if not member:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not a member of this organization"
            )

        from ..models_multitenancy import UserRole
        if member.role != UserRole.OWNER:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only organization owners can create entities"
            )

        # Check entity limit
        existing_entities = service.list_entities(org_id)
        current_count = len(existing_entities)
        within_limit, max_allowed = service.check_limit(org_id, "max_entities", current_count + 1)

        if not within_limit:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Entity limit reached ({current_count}/{max_allowed}). Upgrade to add more entities."
            )

        # Create entity
        entity_data = request.model_dump(exclude_none=True)
        if 'entity_type' in entity_data and entity_data['entity_type']:
            entity_data['entity_type'] = entity_data['entity_type'].value

        entity = service.create_entity(org_id, entity_data)

        return EntityResponse(**entity.model_dump())

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create entity: {str(e)}"
        )


@router.get("/", response_model=List[EntityResponse])
async def list_entities(
    org_id: str = Depends(get_current_organization_id),
    current_user_id: str = Depends(get_current_user_id),
    service: OrganizationService = Depends(get_service)
):
    """
    List all entities for organization

    User must be a member of the organization
    """
    try:
        # Check membership
        member = service.get_organization_member(org_id, current_user_id)
        if not member:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not a member of this organization"
            )

        entities = service.list_entities(org_id)

        return [EntityResponse(**entity.model_dump()) for entity in entities]

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/{entity_id}", response_model=EntityResponse)
async def get_entity(
    entity_id: str,
    org_id: str = Depends(get_current_organization_id),
    current_user_id: str = Depends(get_current_user_id),
    service: OrganizationService = Depends(get_service)
):
    """
    Get entity details

    User must be a member of the organization
    """
    try:
        # Check membership
        member = service.get_organization_member(org_id, current_user_id)
        if not member:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not a member of this organization"
            )

        entity = service.get_entity(entity_id)
        if not entity:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Entity {entity_id} not found"
            )

        # Verify entity belongs to org
        if entity.organization_id != org_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Entity does not belong to this organization"
            )

        return EntityResponse(**entity.model_dump())

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.patch("/{entity_id}", response_model=EntityResponse)
async def update_entity(
    entity_id: str,
    request: UpdateEntityRequest,
    org_id: str = Depends(get_current_organization_id),
    current_user_id: str = Depends(get_current_user_id),
    service: OrganizationService = Depends(get_service)
):
    """
    Update entity details

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

        from ..models_multitenancy import UserRole
        if member.role not in [UserRole.OWNER, UserRole.ADMIN]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only owners and admins can update entities"
            )

        # Get entity and verify ownership
        entity = service.get_entity(entity_id)
        if not entity:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Entity {entity_id} not found"
            )

        if entity.organization_id != org_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Entity does not belong to this organization"
            )

        # Build updates
        updates = request.model_dump(exclude_none=True)
        if not updates:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No fields to update"
            )

        # Convert entity_type enum to string
        if 'entity_type' in updates and updates['entity_type']:
            updates['entity_type'] = updates['entity_type'].value

        # Update entity
        import sqlite3
        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
        values = list(updates.values()) + [entity_id]

        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                f"UPDATE entities SET {set_clause} WHERE id = ?",
                values
            )
            conn.commit()

        # Fetch updated entity
        updated_entity = service.get_entity(entity_id)

        return EntityResponse(**updated_entity.model_dump())

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.delete("/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entity(
    entity_id: str,
    org_id: str = Depends(get_current_organization_id),
    current_user_id: str = Depends(get_current_user_id),
    service: OrganizationService = Depends(get_service)
):
    """
    Delete (deactivate) entity

    Requires: Owner role
    Cannot delete if it's the only entity
    """
    try:
        # Check permissions - only Owner
        member = service.get_organization_member(org_id, current_user_id)
        if not member:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not a member of this organization"
            )

        from ..models_multitenancy import UserRole
        if member.role != UserRole.OWNER:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only organization owners can delete entities"
            )

        # Get entity and verify ownership
        entity = service.get_entity(entity_id)
        if not entity:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Entity {entity_id} not found"
            )

        if entity.organization_id != org_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Entity does not belong to this organization"
            )

        # Check if it's the only entity
        entities = service.list_entities(org_id)
        if len(entities) <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete the only entity. Organizations must have at least one entity."
            )

        # Soft delete (set is_active = 0)
        import sqlite3
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "UPDATE entities SET is_active = 0 WHERE id = ?",
                (entity_id,)
            )
            conn.commit()

        return None

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
