# Multi-Tenancy API Documentation

**Version:** 1.0
**Date:** December 22, 2025

Complete API documentation for ReconAI's multi-tenant architecture with organizations, users, entities, and role-based access control.

---

## Table of Contents

1. [Authentication](#authentication)
2. [Organizations](#organizations)
3. [Entities](#entities)
4. [Members & Roles](#members--roles)
5. [Feature Flags & Limits](#feature-flags--limits)
6. [RBAC (Role-Based Access Control)](#rbac-role-based-access-control)
7. [Integration Examples](#integration-examples)

---

## Authentication

### Overview

ReconAI uses **Clerk** for authentication, providing:
- OAuth integration (Google, GitHub, etc.)
- Email/password authentication
- JWT-based session management
- Multi-factor authentication (MFA)

All API requests (except `/signup`) require a valid JWT token in the `Authorization` header:

```
Authorization: Bearer <jwt_token>
```

### Base URL

```
Development: http://localhost:8000
Production: https://your-api-domain.com
```

---

### POST `/api/auth/signup`

Complete user signup after Clerk authentication.

**Request Body:**
```json
{
  "email": "john@veteranbiz.com",
  "clerk_user_id": "user_2abc123xyz",
  "first_name": "John",
  "last_name": "Smith",
  "organization_name": "Veteran Consulting LLC",
  "organization_slug": "veteran-consulting",
  "tier": "freelancer",
  "industry": "veteran_business"
}
```

**Response (201 Created):**
```json
{
  "user": {
    "id": "user-abc123",
    "email": "john@veteranbiz.com",
    "first_name": "John",
    "last_name": "Smith",
    "default_org_id": "org-xyz789",
    "is_active": true,
    "email_verified": true,
    "created_at": "2025-12-22T10:00:00Z"
  },
  "organization_id": "org-xyz789",
  "message": "Account created successfully with 14-day trial"
}
```

**Errors:**
- `409 Conflict` - User or organization slug already exists
- `400 Bad Request` - Invalid input data

---

### GET `/api/auth/me`

Get current authenticated user's profile.

**Headers:**
```
Authorization: Bearer <jwt_token>
```

**Response (200 OK):**
```json
{
  "id": "user-abc123",
  "email": "john@veteranbiz.com",
  "first_name": "John",
  "last_name": "Smith",
  "avatar_url": "https://...",
  "default_org_id": "org-xyz789",
  "is_active": true,
  "email_verified": true,
  "created_at": "2025-12-22T10:00:00Z"
}
```

---

### POST `/api/auth/verify`

Verify JWT token validity.

**Headers:**
```
Authorization: Bearer <jwt_token>
```

**Response (200 OK):**
```json
{
  "valid": true,
  "user_id": "user_2abc123xyz",
  "email": "john@veteranbiz.com",
  "exp": 1735200000
}
```

---

### GET `/api/auth/session`

Get complete session info including user and organizations.

**Response (200 OK):**
```json
{
  "user": {
    "id": "user-abc123",
    "email": "john@veteranbiz.com",
    "first_name": "John",
    "last_name": "Smith",
    "email_verified": true
  },
  "default_organization": {
    "id": "org-xyz789",
    "name": "Veteran Consulting LLC",
    "slug": "veteran-consulting",
    "tier": "freelancer",
    "features": {
      "invoicing": true,
      "multi_user": false,
      "max_users": 1,
      "max_entities": 1
    }
  },
  "organizations": [
    {
      "id": "org-xyz789",
      "name": "Veteran Consulting LLC",
      "slug": "veteran-consulting",
      "tier": "freelancer"
    }
  ]
}
```

---

## Organizations

Organizations are the top-level tenant in the multi-tenancy system. Each organization has:
- Subscription tier (Individual, Freelancer, Small Business, Professional, Enterprise)
- Feature flags based on tier
- Members with roles and permissions
- One or more entities (legal entities/companies)

---

### POST `/api/organizations`

Create new organization. **Note:** This is typically done during signup. Use this endpoint only for creating additional organizations.

**Request Body:**
```json
{
  "name": "Smith Enterprises",
  "slug": "smith-enterprises",
  "owner_email": "john@smithenterprises.com",
  "tier": "small_business",
  "industry": "professional_services"
}
```

**Response (201 Created):**
```json
{
  "organization": {
    "id": "org-def456",
    "name": "Smith Enterprises",
    "slug": "smith-enterprises",
    "tier": "small_business",
    "industry": "professional_services",
    "subscription_status": "trial",
    "trial_ends_at": "2026-01-05T10:00:00Z",
    "features": {
      "full_accounting": true,
      "multi_user": true,
      "max_users": 5,
      "role_based_access": true
    },
    "created_at": "2025-12-22T10:00:00Z"
  },
  "user": {
    "id": "user-abc123",
    "email": "john@smithenterprises.com"
  },
  "message": "Organization 'Smith Enterprises' created successfully with 14-day trial"
}
```

**Errors:**
- `409 Conflict` - Slug already taken

---

### GET `/api/organizations`

List all organizations the current user belongs to.

**Response (200 OK):**
```json
[
  {
    "id": "org-xyz789",
    "name": "Veteran Consulting LLC",
    "slug": "veteran-consulting",
    "tier": "freelancer",
    "subscription_status": "active",
    "created_at": "2025-12-22T10:00:00Z"
  },
  {
    "id": "org-def456",
    "name": "Smith Enterprises",
    "slug": "smith-enterprises",
    "tier": "small_business",
    "subscription_status": "trial",
    "created_at": "2025-12-22T11:00:00Z"
  }
]
```

---

### GET `/api/organizations/{org_id}`

Get organization details.

**Response (200 OK):**
```json
{
  "id": "org-xyz789",
  "name": "Veteran Consulting LLC",
  "slug": "veteran-consulting",
  "tier": "freelancer",
  "industry": "veteran_business",
  "subscription_status": "active",
  "trial_ends_at": null,
  "subscription_ends_at": "2026-01-22T10:00:00Z",
  "features": {
    "invoicing": true,
    "bill_tracking": true,
    "expense_tracking": true,
    "multi_user": false,
    "max_users": 1,
    "max_entities": 1,
    "max_bank_accounts": 3,
    "max_transactions_per_month": 999999,
    "data_retention_years": 3
  },
  "owner_user_id": "user-abc123",
  "created_at": "2025-12-22T10:00:00Z",
  "updated_at": "2025-12-22T10:00:00Z"
}
```

**Errors:**
- `403 Forbidden` - Not a member of organization
- `404 Not Found` - Organization doesn't exist

---

### PATCH `/api/organizations/{org_id}`

Update organization details. **Requires:** Owner or Admin role.

**Request Body:**
```json
{
  "name": "Veteran Consulting Group",
  "industry": "government_contractor"
}
```

**Response (200 OK):**
```json
{
  "id": "org-xyz789",
  "name": "Veteran Consulting Group",
  "industry": "government_contractor",
  "updated_at": "2025-12-22T15:00:00Z"
}
```

**Tier Changes:**
Only Owner can change tier:
```json
{
  "tier": "professional"
}
```

**Errors:**
- `403 Forbidden` - Insufficient permissions
- `400 Bad Request` - No valid fields to update

---

## Entities

Entities represent legal business entities within an organization (e.g., different LLCs, subsidiaries). Available on **Professional tier and above**.

---

### POST `/api/entities?org_id={org_id}`

Create new entity. **Requires:** Owner role + multi_entity feature.

**Request Body:**
```json
{
  "name": "Smith Consulting LLC",
  "legal_name": "Smith Consulting, LLC",
  "ein": "12-3456789",
  "entity_type": "llc",
  "industry": "professional_services",
  "address_line1": "123 Main St",
  "city": "Arlington",
  "state": "VA",
  "zip": "22201",
  "country": "US",
  "default_currency": "USD"
}
```

**Response (201 Created):**
```json
{
  "id": "entity-ghi789",
  "organization_id": "org-xyz789",
  "name": "Smith Consulting LLC",
  "legal_name": "Smith Consulting, LLC",
  "ein": "12-3456789",
  "entity_type": "llc",
  "default_currency": "USD",
  "is_active": true,
  "created_at": "2025-12-22T10:00:00Z"
}
```

**Errors:**
- `402 Payment Required` - Multi-entity feature not available on current tier
- `402 Payment Required` - Entity limit reached
- `403 Forbidden` - Only owners can create entities

---

### GET `/api/entities?org_id={org_id}`

List all entities for organization.

**Response (200 OK):**
```json
[
  {
    "id": "entity-abc123",
    "organization_id": "org-xyz789",
    "name": "Veteran Consulting LLC",
    "legal_name": "Veteran Consulting LLC",
    "ein": "98-7654321",
    "entity_type": "llc",
    "is_active": true,
    "created_at": "2025-12-22T10:00:00Z"
  },
  {
    "id": "entity-ghi789",
    "organization_id": "org-xyz789",
    "name": "Smith Consulting LLC",
    "legal_name": "Smith Consulting, LLC",
    "ein": "12-3456789",
    "entity_type": "llc",
    "is_active": true,
    "created_at": "2025-12-22T11:00:00Z"
  }
]
```

---

### GET `/api/entities/{entity_id}?org_id={org_id}`

Get entity details.

**Response (200 OK):**
```json
{
  "id": "entity-abc123",
  "organization_id": "org-xyz789",
  "name": "Veteran Consulting LLC",
  "legal_name": "Veteran Consulting LLC",
  "ein": "98-7654321",
  "entity_type": "llc",
  "industry": "veteran_business",
  "address_line1": "456 Oak Ave",
  "city": "Washington",
  "state": "DC",
  "zip": "20001",
  "country": "US",
  "default_currency": "USD",
  "is_active": true,
  "created_at": "2025-12-22T10:00:00Z"
}
```

---

### PATCH `/api/entities/{entity_id}?org_id={org_id}`

Update entity. **Requires:** Owner or Admin role.

**Request Body:**
```json
{
  "address_line1": "789 New Street",
  "city": "Falls Church",
  "zip": "22042"
}
```

---

### DELETE `/api/entities/{entity_id}?org_id={org_id}`

Deactivate entity. **Requires:** Owner role. Cannot delete if it's the only entity.

**Response (204 No Content)**

---

## Members & Roles

Manage organization members and their roles.

---

### POST `/api/organizations/{org_id}/members`

Add member to organization (invite). **Requires:** manage_users permission.

**Request Body:**
```json
{
  "user_id": "user-def456",
  "role": "bookkeeper"
}
```

**Response (201 Created):**
```json
{
  "id": "member-jkl012",
  "organization_id": "org-xyz789",
  "user_id": "user-def456",
  "role": "bookkeeper",
  "permissions": {
    "create_transactions": true,
    "edit_transactions": true,
    "delete_transactions": false,
    "view_reports": true,
    "manage_users": false
  },
  "joined_at": "2025-12-22T10:00:00Z",
  "is_active": true,
  "user": {
    "id": "user-def456",
    "email": "bookkeeper@veteranbiz.com",
    "first_name": "Jane",
    "last_name": "Doe"
  }
}
```

**Errors:**
- `403 Forbidden` - No permission to manage users
- `402 Payment Required` - User limit reached
- `409 Conflict` - User already a member

---

### GET `/api/organizations/{org_id}/members`

List organization members.

**Response (200 OK):**
```json
[
  {
    "id": "member-abc123",
    "user_id": "user-abc123",
    "role": "owner",
    "joined_at": "2025-12-22T10:00:00Z",
    "user": {
      "email": "john@veteranbiz.com",
      "first_name": "John",
      "last_name": "Smith"
    }
  },
  {
    "id": "member-jkl012",
    "user_id": "user-def456",
    "role": "bookkeeper",
    "joined_at": "2025-12-22T11:00:00Z",
    "user": {
      "email": "bookkeeper@veteranbiz.com",
      "first_name": "Jane",
      "last_name": "Doe"
    }
  }
]
```

---

### PATCH `/api/organizations/{org_id}/members/{user_id}`

Update member role. **Requires:** manage_users permission.

**Request Body:**
```json
{
  "role": "accountant"
}
```

**Restrictions:**
- Cannot change owner role
- Only owner can assign owner role

---

### DELETE `/api/organizations/{org_id}/members/{user_id}`

Remove member from organization. **Requires:** manage_users permission.

**Response (204 No Content)**

**Restrictions:**
- Cannot remove owner

---

## Feature Flags & Limits

Check organization's available features and usage limits.

---

### GET `/api/organizations/{org_id}/features`

Get all feature flags.

**Response (200 OK):**
```json
{
  "organization_id": "org-xyz789",
  "tier": "freelancer",
  "features": {
    "invoicing": true,
    "bill_tracking": true,
    "expense_tracking": true,
    "receipt_scanning": true,
    "mileage_tracking": true,
    "multi_user": false,
    "role_based_access": false,
    "multi_entity": false,
    "full_accounting": false,
    "dcaa_compliance": false,
    "max_users": 1,
    "max_entities": 1,
    "max_bank_accounts": 3,
    "max_transactions_per_month": 999999,
    "data_retention_years": 3,
    "api_access": false,
    "white_label": false
  }
}
```

---

### GET `/api/organizations/{org_id}/features/{feature_name}`

Check specific feature.

**Example:** `/api/organizations/org-xyz789/features/invoicing`

**Response (200 OK):**
```json
{
  "organization_id": "org-xyz789",
  "feature": "invoicing",
  "enabled": true
}
```

---

## RBAC (Role-Based Access Control)

ReconAI implements granular role-based permissions.

### Roles

| Role | Description | Default Permissions |
|------|-------------|-------------------|
| **Owner** | Full control | All permissions |
| **Admin** | Administrative access | All except billing & entities |
| **Accountant** | Financial oversight | Reports, COA, close periods |
| **Bookkeeper** | Day-to-day accounting | Create/edit transactions |
| **Manager** | Department manager | Department data, approvals |
| **Viewer** | Read-only access | View basic reports |

### Permission Matrix

| Permission | Owner | Admin | Accountant | Bookkeeper | Manager | Viewer |
|-----------|-------|-------|------------|------------|---------|--------|
| manage_users | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| manage_billing | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| create_entities | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| manage_chart_of_accounts | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| create_transactions | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| edit_transactions | ✅ | ✅ | ✅ | ✅ | Dept | ❌ |
| delete_transactions | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| approve_transactions | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ |
| close_periods | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ |
| view_all_reports | ✅ | ✅ | ✅ | Partial | Dept | Basic |
| export_data | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| api_access | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |

### Using RBAC in Your Code

The RBAC middleware provides dependency functions for FastAPI routes:

```python
from app.middleware import require_permission, require_role, require_feature
from app.models_multitenancy import UserRole

# Require specific permission
@router.post("/transactions")
async def create_transaction(
    org_id: str,
    current_user_id: str = Depends(get_current_user_id),
    _: bool = Depends(require_permission("create_transactions"))
):
    # User has create_transactions permission
    pass

# Require specific role
@router.delete("/organization")
async def delete_org(
    org_id: str,
    current_user_id: str = Depends(get_current_user_id),
    _: bool = Depends(require_role(UserRole.OWNER))
):
    # User is Owner
    pass

# Require feature enabled
@router.post("/invoices")
async def create_invoice(
    org_id: str,
    _: bool = Depends(require_feature("invoicing"))
):
    # Organization has invoicing feature
    pass
```

---

## Integration Examples

### Complete Signup Flow

```javascript
// 1. User signs up with Clerk
const { userId, emailAddress } = await clerk.signUp({ /* ... */ });

// 2. Complete ReconAI signup
const response = await fetch('https://api.reconai.com/api/auth/signup', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    email: emailAddress,
    clerk_user_id: userId,
    first_name: 'John',
    last_name: 'Smith',
    organization_name: 'Veteran Consulting LLC',
    organization_slug: 'veteran-consulting',
    tier: 'freelancer',
    industry: 'veteran_business'
  })
});

const { user, organization_id } = await response.json();
// Save organization_id to local storage for future requests
```

---

### Making Authenticated Requests

```javascript
// Get JWT from Clerk
const token = await clerk.session.getToken();

// Make API request
const response = await fetch('https://api.reconai.com/api/organizations/org-xyz789', {
  headers: {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json'
  }
});

const organization = await response.json();
```

---

### Organization Context

```javascript
// Get session info on app load
const session = await fetch('https://api.reconai.com/api/auth/session', {
  headers: { 'Authorization': `Bearer ${token}` }
}).then(r => r.json());

// Display org selector if user has multiple orgs
if (session.organizations.length > 1) {
  showOrgSelector(session.organizations);
}

// Check feature availability
if (session.default_organization.features.invoicing) {
  showInvoicingMenu();
}
```

---

### Multi-Entity Workflow

```javascript
// Check if multi-entity is available
const features = await fetch(
  `https://api.reconai.com/api/organizations/${orgId}/features`,
  { headers: { 'Authorization': `Bearer ${token}` } }
).then(r => r.json());

if (features.features.multi_entity) {
  // List entities
  const entities = await fetch(
    `https://api.reconai.com/api/entities?org_id=${orgId}`,
    { headers: { 'Authorization': `Bearer ${token}` } }
  ).then(r => r.json());

  // Show entity selector
  showEntitySelector(entities);
} else {
  // Show upgrade prompt
  showUpgradePrompt('Professional tier required for multi-entity support');
}
```

---

## Error Handling

All API errors follow this format:

```json
{
  "detail": "Error message describing what went wrong"
}
```

### Common HTTP Status Codes

- `200 OK` - Success
- `201 Created` - Resource created
- `204 No Content` - Success with no response body
- `400 Bad Request` - Invalid input
- `401 Unauthorized` - Missing or invalid authentication
- `402 Payment Required` - Feature/limit requires upgrade
- `403 Forbidden` - Insufficient permissions
- `404 Not Found` - Resource doesn't exist
- `409 Conflict` - Duplicate resource
- `500 Internal Server Error` - Server error

---

## Rate Limiting

Rate limits vary by tier:

| Tier | Requests/minute | Requests/day |
|------|----------------|--------------|
| Individual | 60 | 1,000 |
| Freelancer | 120 | 5,000 |
| Small Business | 300 | 20,000 |
| Professional | 600 | 100,000 |
| Enterprise | Unlimited | Unlimited |

Rate limit headers are included in responses:
```
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 45
X-RateLimit-Reset: 1735200000
```

---

## Webhooks

Subscribe to organization events (Professional tier+):

- `organization.created`
- `organization.updated`
- `member.added`
- `member.removed`
- `subscription.upgraded`
- `subscription.downgraded`

Configure webhooks in organization settings or via API.

---

## Support

- **Documentation:** https://docs.reconai.com
- **API Status:** https://status.reconai.com
- **Support Email:** support@reconai.com
- **Veterans Support:** veterans@reconai.com (Priority support for veteran-owned businesses)

---

**Built with ❤️ for veterans, small businesses, and enterprises**
