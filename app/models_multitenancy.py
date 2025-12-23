# app/models_multitenancy.py

"""
Multi-Tenancy Models for ReconAI

Supports scaling from Individual to Enterprise:
- Organizations (tenants)
- Users with multi-org membership
- Entities (companies within organizations)
- Role-Based Access Control (RBAC)
- Feature flags based on tier
- Industry templates
"""

from __future__ import annotations
from datetime import datetime, date
from typing import Optional, List, Dict, Any, Literal
from enum import Enum
from pydantic import BaseModel, Field, EmailStr


# =============================================================================
# ENUMS
# =============================================================================

class SubscriptionTier(str, Enum):
    """Subscription tiers with increasing features"""
    INDIVIDUAL = "individual"           # Personal, $0-9/mo
    FREELANCER = "freelancer"           # 1099, $29/mo
    SMALL_BUSINESS = "small_business"   # LLC/S-Corp, $99/mo
    PROFESSIONAL = "professional"       # Teams, $299/mo
    ENTERPRISE = "enterprise"           # Custom pricing


class Industry(str, Enum):
    """Industry templates for pre-configured setups"""
    GENERAL = "general"
    GOVERNMENT_CONTRACTOR = "government_contractor"
    VETERAN_BUSINESS = "veteran_business"
    LAW_ENFORCEMENT = "law_enforcement"
    HEALTHCARE = "healthcare"
    REAL_ESTATE = "real_estate"
    ECOMMERCE = "ecommerce"
    PROFESSIONAL_SERVICES = "professional_services"
    CONSTRUCTION = "construction"
    RETAIL = "retail"


class UserRole(str, Enum):
    """Roles for organization members"""
    OWNER = "owner"              # Full control
    ADMIN = "admin"              # Manage operations
    ACCOUNTANT = "accountant"    # Financial access
    BOOKKEEPER = "bookkeeper"    # Transaction recording
    MANAGER = "manager"          # Department oversight
    VIEWER = "viewer"            # Read-only


class EntityType(str, Enum):
    """Legal entity types"""
    SOLE_PROPRIETOR = "sole_proprietor"
    PARTNERSHIP = "partnership"
    LLC = "llc"
    S_CORP = "s_corp"
    C_CORP = "c_corp"
    NONPROFIT = "nonprofit"


class DimensionType(str, Enum):
    """Types of tracking dimensions"""
    DEPARTMENT = "department"
    CLASS = "class"
    LOCATION = "location"
    PROJECT = "project"
    CUSTOM = "custom"


class SubscriptionStatus(str, Enum):
    """Subscription status"""
    TRIAL = "trial"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"


# =============================================================================
# ORGANIZATION (TENANT)
# =============================================================================

class OrganizationBranding(BaseModel):
    """White-label branding configuration"""
    logo_url: Optional[str] = None
    favicon_url: Optional[str] = None
    primary_color: str = "#1E40AF"
    secondary_color: str = "#3B82F6"
    company_name: Optional[str] = None
    custom_domain: Optional[str] = None
    email_from_name: Optional[str] = None
    email_from_address: Optional[EmailStr] = None
    support_email: Optional[EmailStr] = None
    support_url: Optional[str] = None
    terms_url: Optional[str] = None
    privacy_url: Optional[str] = None


class FeatureFlags(BaseModel):
    """Feature availability based on tier"""
    # Core features
    invoicing: bool = False
    bill_tracking: bool = False
    full_accounting: bool = False
    payroll_integration: bool = False

    # Multi-user
    multi_user: bool = False
    max_users: int = 1
    role_based_access: bool = False
    approval_workflows: bool = False

    # Multi-entity
    multi_entity: bool = False
    max_entities: int = 1
    consolidated_reporting: bool = False

    # Advanced
    multi_currency: bool = False
    department_tracking: bool = False
    max_departments: int = 0
    custom_fields: bool = False
    api_access: bool = False
    white_label: bool = False

    # Industry-specific
    dcaa_compliance: bool = False
    hipaa_compliance: bool = False
    va_benefits_tracking: bool = False
    grant_tracking: bool = False

    # Integrations
    max_bank_accounts: int = 1
    integrations_enabled: List[str] = Field(default_factory=list)

    # Storage & Limits
    max_transactions_per_month: int = 500
    data_retention_years: int = 1
    file_storage_gb: int = 1


class Organization(BaseModel):
    """
    Organization (Tenant) - Core multi-tenancy entity.

    Each organization is isolated and has its own:
    - Users (members)
    - Entities (companies)
    - Data (accounts, transactions, etc.)
    - Settings (branding, features)
    """
    id: Optional[str] = None
    name: str = Field(..., description="Organization name")
    slug: str = Field(..., description="URL-safe slug for subdomain")

    # Subscription
    tier: SubscriptionTier = Field(SubscriptionTier.INDIVIDUAL, description="Subscription tier")
    subscription_status: SubscriptionStatus = Field(SubscriptionStatus.TRIAL, description="Current status")
    trial_ends_at: Optional[datetime] = None
    subscription_ends_at: Optional[datetime] = None

    # Industry
    industry: Optional[Industry] = Field(None, description="Industry for templates")

    # Features
    features: FeatureFlags = Field(default_factory=FeatureFlags, description="Enabled features")

    # Branding
    branding: OrganizationBranding = Field(default_factory=OrganizationBranding, description="White-label branding")

    # Metadata
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    # Owner
    owner_user_id: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Veteran Consulting LLC",
                "slug": "veteran-consulting",
                "tier": "freelancer",
                "industry": "veteran_business",
                "subscription_status": "active"
            }
        }


# =============================================================================
# USER
# =============================================================================

class User(BaseModel):
    """
    User - Can belong to multiple organizations.
    """
    id: Optional[str] = None
    email: EmailStr = Field(..., description="Email address (unique)")
    password_hash: Optional[str] = Field(None, description="Hashed password")

    # Profile
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    avatar_url: Optional[str] = None

    # Multi-org support
    default_org_id: Optional[str] = Field(None, description="Default organization")

    # Status
    is_active: bool = True
    email_verified: bool = False
    last_login_at: Optional[datetime] = None

    # Metadata
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    class Config:
        json_schema_extra = {
            "example": {
                "email": "john@example.com",
                "first_name": "John",
                "last_name": "Doe",
                "default_org_id": "org-123"
            }
        }


# =============================================================================
# ORGANIZATION MEMBERSHIP
# =============================================================================

class Permissions(BaseModel):
    """Granular permissions for users"""
    # Users & Settings
    manage_users: bool = False
    manage_billing: bool = False
    manage_integrations: bool = False

    # Entities & Structure
    create_entities: bool = False
    manage_chart_of_accounts: bool = False
    manage_departments: bool = False

    # Transactions
    create_transactions: bool = True
    approve_transactions: bool = False
    delete_transactions: bool = False
    void_transactions: bool = False

    # Banking
    connect_bank_accounts: bool = False
    reconcile_accounts: bool = False

    # AR/AP
    create_invoices: bool = False
    record_payments: bool = False
    create_bills: bool = False
    approve_bills: bool = False

    # Reporting
    view_reports: List[str] = Field(default_factory=lambda: ["basic"])
    export_data: bool = False
    view_audit_trail: bool = False

    # Period Close
    close_periods: bool = False

    # Payroll
    view_payroll: bool = False
    process_payroll: bool = False

    # Advanced
    api_access: bool = False
    bulk_import: bool = False
    custom_fields: bool = False


class OrganizationMember(BaseModel):
    """
    Many-to-many relationship: User <-> Organization

    Tracks user membership in organizations with role and permissions.
    """
    id: Optional[str] = None
    organization_id: str = Field(..., description="Organization ID")
    user_id: str = Field(..., description="User ID")

    # Role & Permissions
    role: UserRole = Field(..., description="User's role in this organization")
    permissions: Permissions = Field(default_factory=Permissions, description="Granular permissions")

    # Invitation
    invited_by: Optional[str] = Field(None, description="User ID who invited")
    invited_at: Optional[datetime] = None
    joined_at: datetime = Field(default_factory=datetime.now)

    # Status
    is_active: bool = True

    class Config:
        json_schema_extra = {
            "example": {
                "organization_id": "org-123",
                "user_id": "user-456",
                "role": "accountant"
            }
        }


# =============================================================================
# ENTITY (COMPANY)
# =============================================================================

class Entity(BaseModel):
    """
    Entity - A company/legal entity within an organization.

    Organizations can have multiple entities (e.g., multiple LLCs, divisions).
    """
    id: Optional[str] = None
    organization_id: str = Field(..., description="Parent organization")

    # Basic Info
    name: str = Field(..., description="Entity name")
    legal_name: Optional[str] = Field(None, description="Legal business name")
    ein: Optional[str] = Field(None, description="Employer Identification Number")
    entity_type: Optional[EntityType] = Field(None, description="Legal entity type")
    industry: Optional[Industry] = Field(None, description="Industry classification")

    # Address
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    country: str = "US"

    # Contact
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    website: Optional[str] = None

    # Tax Info
    fiscal_year_end: Optional[str] = Field(None, description="MM-DD format, e.g., '12-31'")
    tax_id_type: Optional[str] = Field(None, description="SSN or EIN")

    # Settings
    default_currency: str = "USD"
    timezone: str = "America/New_York"

    # Status
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    class Config:
        json_schema_extra = {
            "example": {
                "organization_id": "org-123",
                "name": "Acme LLC",
                "legal_name": "Acme Consulting, LLC",
                "ein": "12-3456789",
                "entity_type": "llc",
                "industry": "professional_services"
            }
        }


# =============================================================================
# DIMENSIONS (DEPARTMENT, CLASS, LOCATION, etc.)
# =============================================================================

class Dimension(BaseModel):
    """
    Dimension - Track transactions by department, class, location, project, etc.

    Supports hierarchical structure (parent/child).
    """
    id: Optional[str] = None
    organization_id: str = Field(..., description="Parent organization")
    entity_id: Optional[str] = Field(None, description="Parent entity (optional)")

    # Type & Info
    dimension_type: DimensionType = Field(..., description="Type of dimension")
    name: str = Field(..., description="Dimension name")
    code: Optional[str] = Field(None, description="Short code for reporting")
    description: Optional[str] = None

    # Hierarchy
    parent_id: Optional[str] = Field(None, description="Parent dimension for hierarchies")

    # Status
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.now)

    class Config:
        json_schema_extra = {
            "example": {
                "organization_id": "org-123",
                "entity_id": "entity-456",
                "dimension_type": "department",
                "name": "Marketing",
                "code": "MKT"
            }
        }


# =============================================================================
# CUSTOM FIELDS
# =============================================================================

class CustomField(BaseModel):
    """
    Custom Field - User-defined fields for any entity type.

    Examples:
    - Customer: "Preferred payment method"
    - Invoice: "Project number"
    - Transaction: "Approval status"
    """
    id: Optional[str] = None
    organization_id: str = Field(..., description="Parent organization")

    # Field Definition
    entity_type: str = Field(..., description="customer, vendor, invoice, transaction, etc.")
    field_name: str = Field(..., description="Field name")
    field_type: Literal["text", "number", "date", "dropdown", "checkbox"] = Field(..., description="Data type")
    field_options: Optional[List[str]] = Field(None, description="Options for dropdown")

    # Validation
    is_required: bool = False
    default_value: Optional[str] = None

    # Display
    display_order: int = 0
    help_text: Optional[str] = None

    # Status
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.now)

    class Config:
        json_schema_extra = {
            "example": {
                "organization_id": "org-123",
                "entity_type": "customer",
                "field_name": "Industry",
                "field_type": "dropdown",
                "field_options": ["Technology", "Healthcare", "Retail"]
            }
        }


class CustomFieldValue(BaseModel):
    """Value for a custom field on a specific record"""
    id: Optional[str] = None
    custom_field_id: str = Field(..., description="Custom field definition")
    record_id: str = Field(..., description="ID of the record (customer, invoice, etc.)")
    value: Optional[str] = None


# =============================================================================
# APPROVAL WORKFLOWS
# =============================================================================

class ApprovalRule(BaseModel):
    """
    Approval Rule - Define when transactions need approval.

    Examples:
    - Bills over $1,000 need manager approval
    - All journal entries need accountant approval
    - Marketing expenses need CMO approval
    """
    id: Optional[str] = None
    organization_id: str = Field(..., description="Parent organization")
    entity_id: Optional[str] = Field(None, description="Entity (optional)")

    # Rule
    transaction_type: str = Field(..., description="bill, expense, journal_entry, etc.")
    condition: Dict[str, Any] = Field(..., description="JSON condition, e.g., {'amount_over': 1000}")

    # Approver
    requires_approval_from: str = Field(..., description="Role or user_id")
    approval_order: int = Field(1, description="For multi-level approvals")

    # Status
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.now)


class Approval(BaseModel):
    """
    Approval - Track approval status for a transaction.
    """
    id: Optional[str] = None
    transaction_id: str = Field(..., description="Transaction being approved")
    transaction_type: str = Field(..., description="Type of transaction")

    # Approval
    required_approver_id: str = Field(..., description="Who must approve")
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None

    # Status
    status: Literal["pending", "approved", "rejected"] = "pending"
    notes: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.now)


# =============================================================================
# TIER CONFIGURATION
# =============================================================================

TIER_CONFIGS = {
    SubscriptionTier.INDIVIDUAL: {
        "price_monthly": 0,
        "price_yearly": 0,
        "features": FeatureFlags(
            invoicing=False,
            bill_tracking=False,
            full_accounting=False,
            multi_user=False,
            max_users=1,
            max_entities=1,
            max_bank_accounts=1,
            max_transactions_per_month=500,
            data_retention_years=1,
            file_storage_gb=1,
        ),
        "limits": {
            "customers": 0,
            "vendors": 0,
        }
    },

    SubscriptionTier.FREELANCER: {
        "price_monthly": 29,
        "price_yearly": 290,
        "features": FeatureFlags(
            invoicing=True,
            bill_tracking=True,
            full_accounting=False,
            multi_user=False,
            max_users=1,
            max_entities=1,
            max_bank_accounts=3,
            max_transactions_per_month=999999,  # unlimited
            data_retention_years=3,
            file_storage_gb=5,
        ),
        "limits": {
            "customers": 50,
            "vendors": 25,
        }
    },

    SubscriptionTier.SMALL_BUSINESS: {
        "price_monthly": 99,
        "price_yearly": 990,
        "features": FeatureFlags(
            invoicing=True,
            bill_tracking=True,
            full_accounting=True,
            payroll_integration=True,
            multi_user=True,
            max_users=5,
            role_based_access=True,
            approval_workflows=True,
            max_entities=1,
            department_tracking=True,
            max_departments=3,
            max_bank_accounts=10,
            max_transactions_per_month=999999,
            data_retention_years=7,
            file_storage_gb=25,
            api_access=True,
        ),
        "limits": {
            "customers": 999999,
            "vendors": 999999,
        }
    },

    SubscriptionTier.PROFESSIONAL: {
        "price_monthly": 299,
        "price_yearly": 2990,
        "features": FeatureFlags(
            invoicing=True,
            bill_tracking=True,
            full_accounting=True,
            payroll_integration=True,
            multi_user=True,
            max_users=25,
            role_based_access=True,
            approval_workflows=True,
            multi_entity=True,
            max_entities=5,
            consolidated_reporting=True,
            multi_currency=True,
            department_tracking=True,
            max_departments=999999,
            custom_fields=True,
            max_bank_accounts=50,
            max_transactions_per_month=999999,
            data_retention_years=999,
            file_storage_gb=100,
            api_access=True,
        ),
        "limits": {
            "customers": 999999,
            "vendors": 999999,
        }
    },

    SubscriptionTier.ENTERPRISE: {
        "price_monthly": 999,
        "price_yearly": 9990,
        "features": FeatureFlags(
            # Everything unlimited
            invoicing=True,
            bill_tracking=True,
            full_accounting=True,
            payroll_integration=True,
            multi_user=True,
            max_users=999999,
            role_based_access=True,
            approval_workflows=True,
            multi_entity=True,
            max_entities=999999,
            consolidated_reporting=True,
            multi_currency=True,
            department_tracking=True,
            max_departments=999999,
            custom_fields=True,
            white_label=True,
            max_bank_accounts=999999,
            max_transactions_per_month=999999,
            data_retention_years=999,
            file_storage_gb=999999,
            api_access=True,
        ),
        "limits": {
            "customers": 999999,
            "vendors": 999999,
        }
    }
}


# =============================================================================
# ROLE PERMISSIONS PRESETS
# =============================================================================

ROLE_PERMISSIONS = {
    UserRole.OWNER: Permissions(
        manage_users=True,
        manage_billing=True,
        manage_integrations=True,
        create_entities=True,
        manage_chart_of_accounts=True,
        manage_departments=True,
        create_transactions=True,
        approve_transactions=True,
        delete_transactions=True,
        void_transactions=True,
        connect_bank_accounts=True,
        reconcile_accounts=True,
        create_invoices=True,
        record_payments=True,
        create_bills=True,
        approve_bills=True,
        view_reports=["all"],
        export_data=True,
        view_audit_trail=True,
        close_periods=True,
        view_payroll=True,
        process_payroll=True,
        api_access=True,
        bulk_import=True,
        custom_fields=True,
    ),

    UserRole.ADMIN: Permissions(
        manage_users=True,
        manage_integrations=True,
        create_entities=False,
        manage_chart_of_accounts=True,
        manage_departments=True,
        create_transactions=True,
        approve_transactions=True,
        delete_transactions=False,
        void_transactions=True,
        connect_bank_accounts=True,
        reconcile_accounts=True,
        create_invoices=True,
        record_payments=True,
        create_bills=True,
        approve_bills=True,
        view_reports=["all"],
        export_data=True,
        view_audit_trail=True,
        close_periods=False,
        view_payroll=True,
        bulk_import=True,
    ),

    UserRole.ACCOUNTANT: Permissions(
        manage_chart_of_accounts=True,
        create_transactions=True,
        approve_transactions=True,
        void_transactions=True,
        reconcile_accounts=True,
        create_invoices=True,
        record_payments=True,
        create_bills=True,
        approve_bills=True,
        view_reports=["all"],
        export_data=True,
        view_audit_trail=True,
        close_periods=True,
        bulk_import=True,
    ),

    UserRole.BOOKKEEPER: Permissions(
        create_transactions=True,
        reconcile_accounts=True,
        create_invoices=True,
        record_payments=True,
        create_bills=True,
        view_reports=["basic", "ar", "ap"],
        export_data=False,
    ),

    UserRole.MANAGER: Permissions(
        create_transactions=True,
        approve_transactions=True,
        approve_bills=True,
        view_reports=["department", "budget"],
    ),

    UserRole.VIEWER: Permissions(
        view_reports=["basic"],
    ),
}
