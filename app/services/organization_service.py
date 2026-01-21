# app/services/organization_service.py

"""
Organization Service - Multi-tenancy core logic

Handles:
- Organization CRUD
- User management
- Entity management
- Feature flag checks
- Tier management
"""

from __future__ import annotations
import sqlite3
import json
import uuid
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from pathlib import Path

from ..models_multitenancy import (
    Organization, User, OrganizationMember, Entity,
    SubscriptionTier, UserRole, FeatureFlags,
    TIER_CONFIGS, ROLE_PERMISSIONS
)
from ..db import DB_PATH


class OrganizationService:
    """Service for managing organizations and multi-tenancy"""

    def __init__(self, db_path: str | Path = DB_PATH):
        self.db_path = Path(db_path)

    # =========================================================================
    # ORGANIZATION MANAGEMENT
    # =========================================================================

    def create_organization(
        self,
        name: str,
        slug: str,
        owner_email: str,
        tier: SubscriptionTier = SubscriptionTier.INDIVIDUAL,
        industry: Optional[str] = None
    ) -> tuple[Organization, User]:
        """
        Create a new organization with owner user.

        Returns:
            (organization, owner_user)
        """
        org_id = f"org-{uuid.uuid4().hex[:12]}"
        user_id = f"user-{uuid.uuid4().hex[:12]}"

        # Get tier configuration
        tier_config = TIER_CONFIGS[tier]
        features = tier_config["features"]

        # Set trial period (14 days)
        trial_ends_at = datetime.now() + timedelta(days=14)

        with sqlite3.connect(self.db_path) as conn:
            # Create organization
            conn.execute("""
                INSERT INTO organizations (
                    id, name, slug, tier, industry, subscription_status,
                    trial_ends_at, features, owner_user_id
                ) VALUES (?, ?, ?, ?, ?, 'trial', ?, ?, ?)
            """, (
                org_id, name, slug, tier.value, industry,
                trial_ends_at.isoformat(), json.dumps(features.model_dump()),
                user_id
            ))

            # Create owner user (password will be set separately)
            conn.execute("""
                INSERT INTO users (
                    id, email, password_hash, default_org_id, is_active, email_verified
                ) VALUES (?, ?, '', ?, 1, 0)
            """, (user_id, owner_email, org_id))

            # Add user as organization owner
            member_id = f"member-{uuid.uuid4().hex[:12]}"
            owner_permissions = ROLE_PERMISSIONS[UserRole.OWNER]

            conn.execute("""
                INSERT INTO organization_members (
                    id, organization_id, user_id, role, permissions
                ) VALUES (?, ?, ?, 'owner', ?)
            """, (
                member_id, org_id, user_id,
                json.dumps(owner_permissions.model_dump())
            ))

            # Create default entity
            entity_id = f"entity-{uuid.uuid4().hex[:12]}"
            conn.execute("""
                INSERT INTO entities (
                    id, organization_id, name, legal_name
                ) VALUES (?, ?, ?, ?)
            """, (entity_id, org_id, name, name))

            conn.commit()

        # Return created objects
        org = self.get_organization(org_id)
        user = self.get_user(user_id)
        return org, user

    def get_organization(self, org_id: str) -> Optional[Organization]:
        """Get organization by ID"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM organizations WHERE id = ?",
                (org_id,)
            )
            row = cursor.fetchone()

            if row:
                return Organization(
                    id=row['id'],
                    name=row['name'],
                    slug=row['slug'],
                    tier=SubscriptionTier(row['tier']),
                    industry=row['industry'],
                    subscription_status=row['subscription_status'],
                    trial_ends_at=datetime.fromisoformat(row['trial_ends_at']) if row['trial_ends_at'] else None,
                    subscription_ends_at=datetime.fromisoformat(row['subscription_ends_at']) if row['subscription_ends_at'] else None,
                    features=FeatureFlags(**json.loads(row['features'])),
                    branding=json.loads(row['branding']) if row['branding'] else {},
                    owner_user_id=row['owner_user_id'],
                    created_at=datetime.fromisoformat(row['created_at']),
                    updated_at=datetime.fromisoformat(row['updated_at'])
                )
            return None

    def get_organization_by_slug(self, slug: str) -> Optional[Organization]:
        """Get organization by slug"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT id FROM organizations WHERE slug = ?",
                (slug,)
            )
            row = cursor.fetchone()
            if row:
                return self.get_organization(row[0])
            return None

    def list_user_organizations(self, user_id: str) -> List[Organization]:
        """List all organizations a user belongs to"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT o.id FROM organizations o
                JOIN organization_members m ON o.id = m.organization_id
                WHERE m.user_id = ? AND m.is_active = 1
                ORDER BY m.joined_at DESC
            """, (user_id,))

            org_ids = [row[0] for row in cursor.fetchall()]

        return [self.get_organization(org_id) for org_id in org_ids]

    def update_organization(self, org_id: str, updates: Dict[str, Any]) -> Optional[Organization]:
        """Update organization"""
        allowed_fields = {'name', 'industry', 'tier', 'subscription_status', 'features', 'branding'}
        updates = {k: v for k, v in updates.items() if k in allowed_fields}

        if not updates:
            return self.get_organization(org_id)

        # Convert objects to JSON strings
        if 'features' in updates:
            updates['features'] = json.dumps(updates['features'])
        if 'branding' in updates:
            updates['branding'] = json.dumps(updates['branding'])

        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
        set_clause += ", updated_at = datetime('now')"
        values = list(updates.values()) + [org_id]

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"UPDATE organizations SET {set_clause} WHERE id = ?",
                values
            )
            conn.commit()

        return self.get_organization(org_id)

    # =========================================================================
    # USER MANAGEMENT
    # =========================================================================

    def get_user(self, user_id: str) -> Optional[User]:
        """Get user by ID"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,))
            row = cursor.fetchone()

            if row:
                # P0: Handle profile_completed column which may not exist in older DBs
                profile_completed = False
                try:
                    profile_completed = bool(row['profile_completed'])
                except (KeyError, IndexError):
                    pass

                return User(
                    id=row['id'],
                    email=row['email'],
                    password_hash=row['password_hash'],
                    first_name=row['first_name'],
                    last_name=row['last_name'],
                    phone=row['phone'],
                    avatar_url=row['avatar_url'],
                    default_org_id=row['default_org_id'],
                    is_active=bool(row['is_active']),
                    email_verified=bool(row['email_verified']),
                    profile_completed=profile_completed,
                    last_login_at=datetime.fromisoformat(row['last_login_at']) if row['last_login_at'] else None,
                    created_at=datetime.fromisoformat(row['created_at']),
                    updated_at=datetime.fromisoformat(row['updated_at'])
                )
            return None

    def get_user_by_email(self, email: str) -> Optional[User]:
        """Get user by email"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT id FROM users WHERE email = ?", (email,))
            row = cursor.fetchone()
            if row:
                return self.get_user(row[0])
            return None

    def get_user_by_clerk_id(self, clerk_user_id: str) -> Optional[User]:
        """Get user by Clerk user ID (stored in user_id column)"""
        with sqlite3.connect(self.db_path) as conn:
            # The user_id column stores the Clerk user ID
            cursor = conn.execute("SELECT id FROM users WHERE user_id = ?", (clerk_user_id,))
            row = cursor.fetchone()
            if row:
                return self.get_user(row[0])
            return None

    def auto_provision_personal_user(
        self,
        clerk_user_id: str,
        email: str,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
    ) -> tuple[User, Organization]:
        """
        Auto-provision a new user with a personal workspace.

        Called when a Clerk-authenticated user has no DB record.
        Creates:
        - User record linked to Clerk ID
        - Personal workspace organization (tier=individual)
        - Owner membership in personal workspace
        - Default entity

        Returns:
            (user, personal_workspace_org)
        """
        import logging
        logger = logging.getLogger(__name__)

        # Generate IDs
        user_id = f"user-{uuid.uuid4().hex[:12]}"
        org_id = f"org-personal-{uuid.uuid4().hex[:12]}"
        member_id = f"member-{uuid.uuid4().hex[:12]}"
        entity_id = f"entity-{uuid.uuid4().hex[:12]}"

        # Personal workspace name
        display_name = f"{first_name or ''} {last_name or ''}".strip() or email.split("@")[0]
        workspace_name = f"{display_name}'s Workspace"
        slug = f"personal-{clerk_user_id[:12]}"

        # Get tier configuration for individual
        tier_config = TIER_CONFIGS[SubscriptionTier.INDIVIDUAL]
        features = tier_config["features"]
        owner_permissions = ROLE_PERMISSIONS[UserRole.OWNER]

        # Set trial period (14 days)
        trial_ends_at = datetime.now() + timedelta(days=14)

        logger.info(f"Auto-provisioning personal user: clerk_id={clerk_user_id}, email={email}")

        with sqlite3.connect(self.db_path) as conn:
            try:
                # Create user record
                conn.execute("""
                    INSERT INTO users (
                        id, email, password_hash, first_name, last_name,
                        default_org_id, is_active, email_verified, user_id
                    ) VALUES (?, ?, '', ?, ?, ?, 1, 1, ?)
                """, (user_id, email, first_name, last_name, org_id, clerk_user_id))

                # Create personal workspace organization
                conn.execute("""
                    INSERT INTO organizations (
                        id, name, slug, tier, industry, subscription_status,
                        trial_ends_at, features, owner_user_id
                    ) VALUES (?, ?, ?, 'individual', 'general', 'trial', ?, ?, ?)
                """, (
                    org_id, workspace_name, slug,
                    trial_ends_at.isoformat(), json.dumps(features.model_dump()),
                    user_id
                ))

                # Add user as organization owner
                conn.execute("""
                    INSERT INTO organization_members (
                        id, organization_id, user_id, role, permissions
                    ) VALUES (?, ?, ?, 'owner', ?)
                """, (
                    member_id, org_id, user_id,
                    json.dumps(owner_permissions.model_dump())
                ))

                # Create default entity
                conn.execute("""
                    INSERT INTO entities (
                        id, organization_id, name, legal_name
                    ) VALUES (?, ?, ?, ?)
                """, (entity_id, org_id, "Personal", "Personal"))

                conn.commit()
                logger.info(f"Auto-provisioned user {user_id} with personal workspace {org_id}")

            except sqlite3.IntegrityError as e:
                # Handle race condition - user may have been created by another request
                logger.warning(f"Auto-provision integrity error (may be race condition): {e}")
                conn.rollback()
                # Try to fetch the existing user
                existing_user = self.get_user_by_email(email) or self.get_user_by_clerk_id(clerk_user_id)
                if existing_user:
                    orgs = self.list_user_organizations(existing_user.id)
                    if orgs:
                        return existing_user, orgs[0]
                raise

        # Return created objects
        user = self.get_user(user_id)
        org = self.get_organization(org_id)
        return user, org

    def add_organization_member(
        self,
        org_id: str,
        user_id: str,
        role: UserRole = UserRole.VIEWER,
        invited_by: Optional[str] = None
    ) -> OrganizationMember:
        """Add user to organization"""
        member_id = f"member-{uuid.uuid4().hex[:12]}"
        permissions = ROLE_PERMISSIONS[role]

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO organization_members (
                    id, organization_id, user_id, role, permissions, invited_by, invited_at
                ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            """, (
                member_id, org_id, user_id, role.value,
                json.dumps(permissions.model_dump()), invited_by
            ))
            conn.commit()

        return self.get_organization_member(org_id, user_id)

    def get_organization_member(self, org_id: str, user_id: str) -> Optional[OrganizationMember]:
        """Get organization membership"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM organization_members
                WHERE organization_id = ? AND user_id = ?
            """, (org_id, user_id))
            row = cursor.fetchone()

            if row:
                return OrganizationMember(
                    id=row['id'],
                    organization_id=row['organization_id'],
                    user_id=row['user_id'],
                    role=UserRole(row['role']),
                    permissions=json.loads(row['permissions']) if row['permissions'] else {},
                    invited_by=row['invited_by'],
                    invited_at=datetime.fromisoformat(row['invited_at']) if row['invited_at'] else None,
                    joined_at=datetime.fromisoformat(row['joined_at']),
                    is_active=bool(row['is_active'])
                )
            return None

    def list_organization_members(self, org_id: str) -> List[tuple[OrganizationMember, User]]:
        """List all members of an organization"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT user_id FROM organization_members
                WHERE organization_id = ? AND is_active = 1
                ORDER BY joined_at
            """, (org_id,))

            user_ids = [row[0] for row in cursor.fetchall()]

        result = []
        for user_id in user_ids:
            member = self.get_organization_member(org_id, user_id)
            user = self.get_user(user_id)
            if member and user:
                result.append((member, user))

        return result

    # =========================================================================
    # ENTITY MANAGEMENT
    # =========================================================================

    def create_entity(self, org_id: str, entity_data: Dict[str, Any]) -> Entity:
        """Create entity within organization"""
        entity_id = f"entity-{uuid.uuid4().hex[:12]}"

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO entities (
                    id, organization_id, name, legal_name, ein, entity_type, industry
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                entity_id, org_id,
                entity_data.get('name'),
                entity_data.get('legal_name'),
                entity_data.get('ein'),
                entity_data.get('entity_type'),
                entity_data.get('industry')
            ))
            conn.commit()

        return self.get_entity(entity_id)

    def get_entity(self, entity_id: str) -> Optional[Entity]:
        """Get entity by ID"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM entities WHERE id = ?", (entity_id,))
            row = cursor.fetchone()

            if row:
                return Entity(
                    id=row['id'],
                    organization_id=row['organization_id'],
                    name=row['name'],
                    legal_name=row['legal_name'],
                    ein=row['ein'],
                    entity_type=row['entity_type'],
                    industry=row['industry'],
                    address_line1=row['address_line1'],
                    city=row['city'],
                    state=row['state'],
                    zip=row['zip'],
                    country=row['country'],
                    default_currency=row['default_currency'],
                    is_active=bool(row['is_active']),
                    created_at=datetime.fromisoformat(row['created_at'])
                )
            return None

    def list_entities(self, org_id: str) -> List[Entity]:
        """List all entities for organization"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT id FROM entities
                WHERE organization_id = ? AND is_active = 1
                ORDER BY created_at
            """, (org_id,))

            entity_ids = [row[0] for row in cursor.fetchall()]

        return [self.get_entity(eid) for eid in entity_ids]

    # =========================================================================
    # FEATURE FLAG CHECKS
    # =========================================================================

    def check_feature(self, org_id: str, feature_name: str) -> bool:
        """Check if organization has access to feature"""
        org = self.get_organization(org_id)
        if not org:
            return False

        return getattr(org.features, feature_name, False)

    def check_limit(self, org_id: str, limit_name: str, current_count: int) -> tuple[bool, int]:
        """
        Check if organization is within limit.

        Returns:
            (within_limit, max_allowed)
        """
        org = self.get_organization(org_id)
        if not org:
            return False, 0

        max_allowed = getattr(org.features, limit_name, 0)

        # 999999 = unlimited
        if max_allowed == 999999:
            return True, max_allowed

        return current_count < max_allowed, max_allowed
