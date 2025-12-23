# ReconAI Multi-Tier Architecture
## From Individual to Enterprise

**Vision:** A financial intelligence platform that scales from personal expense tracking to enterprise-grade accounting, with special focus on veterans, military, law enforcement, and government contractors.

---

## 🎯 Core Design Principles

1. **Start Simple, Scale Infinitely** - User starts with basic features, unlocks complexity as needed
2. **Multi-Tenant by Default** - Every user is an "organization" (even individuals)
3. **Industry-Aware** - Templates and workflows tailored to specific industries
4. **Compliance-First** - DCAA, IRS, SOC 2, HIPAA ready from day one
5. **White-Label Ready** - Can be rebranded for resellers/partners

---

## 📊 Tier Structure

### Tier 1: Individual/Personal 👤
**Target:** Personal finance, side hustles, gig workers

**Features:**
- ✅ Expense tracking & categorization
- ✅ Bank account connection (Plaid)
- ✅ Receipt scanning & OCR
- ✅ Basic tax prep (Schedule C)
- ✅ Simple reports (P&L, spending breakdown)
- ✅ Mobile app access
- ❌ No invoicing
- ❌ No multi-user
- ❌ Single entity only

**Limits:**
- 1 user
- 1 bank account
- 500 transactions/month
- 1 year data retention

**Price:** Free or $9/month

---

### Tier 2: Freelancer/Sole Proprietor 💼
**Target:** 1099 contractors, consultants, freelancers, veterans starting businesses

**Features:**
- ✅ Everything in Individual
- ✅ Professional invoicing (unlimited)
- ✅ Customer management
- ✅ Bill tracking & vendor management
- ✅ Schedule C automation
- ✅ Quarterly tax estimates
- ✅ Mileage tracking
- ✅ Home office calculator
- ✅ 1099 generation
- ✅ Chart of accounts (basic)
- ✅ Journal entries (basic)
- ❌ No payroll
- ❌ No multi-user
- ❌ No departments

**Limits:**
- 1 user
- 3 bank accounts
- Unlimited transactions
- 3 years data retention
- 50 customers
- 25 vendors

**Price:** $29/month or $290/year

**Special:** Veterans discount (50% off)

---

### Tier 3: Small Business 🏢
**Target:** LLC, S-Corp, small teams (2-10 employees), veteran-owned businesses

**Features:**
- ✅ Everything in Freelancer
- ✅ **Multi-user (up to 5 users)**
- ✅ Role-based permissions (Owner, Accountant, Bookkeeper, Viewer)
- ✅ **Full double-entry accounting**
- ✅ **Payroll-ready** (integrates with Gusto, ADP)
- ✅ Inventory tracking
- ✅ Project/job costing
- ✅ Department tracking
- ✅ Budget vs actual
- ✅ Cash flow forecasting
- ✅ Approval workflows (bills, expenses)
- ✅ Accountant collaboration portal
- ✅ Custom reports
- ✅ API access (basic)
- ❌ No multi-entity
- ❌ No advanced audit trails

**Limits:**
- 5 users
- 10 bank accounts
- Unlimited transactions
- 7 years data retention
- Unlimited customers/vendors
- 3 departments

**Price:** $99/month or $990/year

**Special:** Government contractor add-on (+$50/month for DCAA compliance)

---

### Tier 4: Professional/Team 🏛️
**Target:** Growing businesses (10-50 employees), law enforcement agencies, healthcare practices

**Features:**
- ✅ Everything in Small Business
- ✅ **Multi-user (up to 25 users)**
- ✅ **Multi-entity/company support** (up to 5 entities)
- ✅ Consolidated reporting across entities
- ✅ Inter-company transactions
- ✅ Advanced approval workflows
- ✅ Custom roles & permissions
- ✅ Department/class/location tracking (unlimited)
- ✅ Custom fields on all records
- ✅ Advanced audit trails (who/what/when)
- ✅ Time tracking & billing
- ✅ Purchase orders
- ✅ Fixed asset management
- ✅ Multi-currency support
- ✅ Advanced API access
- ✅ SSO (Single Sign-On)
- ✅ Dedicated support
- ❌ No white-label

**Limits:**
- 25 users
- 50 bank accounts
- Unlimited transactions
- Unlimited data retention
- 5 entities
- Unlimited departments

**Price:** $299/month or $2,990/year

**Add-ons:**
- DCAA Compliance Suite: +$100/month
- HIPAA Compliance: +$150/month
- SOC 2 Ready: +$200/month

---

### Tier 5: Enterprise 🏰
**Target:** Large organizations (50+ employees), government contractors, multi-state operations

**Features:**
- ✅ **Everything unlimited**
- ✅ Unlimited users
- ✅ Unlimited entities
- ✅ **White-label options**
- ✅ Custom workflows & automation
- ✅ Advanced integrations (custom APIs)
- ✅ Dedicated account manager
- ✅ Custom training
- ✅ On-premise deployment option
- ✅ Advanced security (2FA, IP whitelisting)
- ✅ SLA guarantees
- ✅ Data residency options
- ✅ Custom industry modules
- ✅ BI/Analytics dashboards
- ✅ Advanced forecasting & AI insights

**Price:** Custom (starts at $999/month)

**Available Add-ons:**
- DCAA Full Compliance: Custom pricing
- Federal contractor module: Custom pricing
- Healthcare/HIPAA: Custom pricing
- Multi-national support: Custom pricing

---

## 🏗️ Multi-Tenancy Architecture

### Database Design

```sql
-- Core tenant structure
CREATE TABLE organizations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  slug TEXT UNIQUE NOT NULL, -- for subdomain (acme-corp)
  tier TEXT NOT NULL, -- individual, freelancer, small_business, professional, enterprise
  industry TEXT, -- government_contractor, veteran_business, law_enforcement, etc.
  created_at TIMESTAMPTZ DEFAULT NOW(),

  -- Tier limits
  max_users INTEGER,
  max_entities INTEGER,
  max_bank_accounts INTEGER,
  max_transactions_per_month INTEGER,

  -- Feature flags
  features JSONB DEFAULT '{}', -- {"invoicing": true, "payroll": false, ...}

  -- Branding (for white-label)
  branding JSONB DEFAULT '{}', -- {"logo_url": "", "primary_color": "", ...}

  -- Subscription
  subscription_status TEXT DEFAULT 'active', -- active, trial, suspended, cancelled
  trial_ends_at TIMESTAMPTZ,
  subscription_ends_at TIMESTAMPTZ
);

-- Users belong to organizations
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  first_name TEXT,
  last_name TEXT,

  -- Multi-org support (user can belong to multiple orgs)
  default_org_id UUID REFERENCES organizations(id),

  created_at TIMESTAMPTZ DEFAULT NOW(),
  last_login_at TIMESTAMPTZ
);

-- Many-to-many: Users <-> Organizations
CREATE TABLE organization_members (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL, -- owner, admin, accountant, bookkeeper, viewer
  permissions JSONB DEFAULT '{}', -- granular permissions
  invited_by UUID REFERENCES users(id),
  joined_at TIMESTAMPTZ DEFAULT NOW(),

  UNIQUE(organization_id, user_id)
);

-- Multi-entity support (companies within an organization)
CREATE TABLE entities (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  legal_name TEXT,
  ein TEXT, -- Employer Identification Number
  entity_type TEXT, -- sole_prop, llc, s_corp, c_corp, partnership
  industry TEXT,

  -- Address
  address_line1 TEXT,
  address_line2 TEXT,
  city TEXT,
  state TEXT,
  zip TEXT,
  country TEXT DEFAULT 'US',

  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW(),

  UNIQUE(organization_id, name)
);

-- Department/class/location tracking
CREATE TABLE dimensions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
  entity_id UUID REFERENCES entities(id) ON DELETE CASCADE,

  dimension_type TEXT NOT NULL, -- department, class, location, project, custom
  name TEXT NOT NULL,
  code TEXT, -- optional code for reporting
  parent_id UUID REFERENCES dimensions(id), -- for hierarchies

  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW(),

  UNIQUE(organization_id, entity_id, dimension_type, name)
);

-- Update existing tables to be multi-tenant
-- Example: accounts table
CREATE TABLE accounts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
  entity_id UUID REFERENCES entities(id) ON DELETE CASCADE,

  account_number TEXT NOT NULL,
  account_name TEXT NOT NULL,
  account_type TEXT NOT NULL,
  -- ... rest of fields ...

  UNIQUE(organization_id, entity_id, account_number)
);

-- Row-Level Security (RLS) for PostgreSQL
ALTER TABLE accounts ENABLE ROW LEVEL SECURITY;

CREATE POLICY org_isolation ON accounts
  USING (organization_id = current_setting('app.current_org_id')::UUID);
```

---

## 🔐 Role-Based Access Control (RBAC)

### Default Roles

#### 1. Owner
**Description:** Full control over organization
**Permissions:**
- ✅ Manage billing & subscription
- ✅ Add/remove users
- ✅ Change user roles
- ✅ Create/delete entities
- ✅ All accounting operations
- ✅ View all reports
- ✅ Export data
- ✅ Delete organization

#### 2. Admin
**Description:** Manages day-to-day operations
**Permissions:**
- ✅ Add/remove users (except owners)
- ✅ All accounting operations
- ✅ Approve/reject transactions
- ✅ View all reports
- ✅ Export data
- ❌ Cannot manage billing
- ❌ Cannot delete organization

#### 3. Accountant
**Description:** Financial professional with full books access
**Permissions:**
- ✅ All journal entries
- ✅ Account reconciliation
- ✅ Close periods
- ✅ Generate reports
- ✅ Export data
- ✅ View audit trails
- ❌ Cannot manage users
- ❌ Cannot approve own entries

#### 4. Bookkeeper
**Description:** Day-to-day transaction recording
**Permissions:**
- ✅ Create journal entries (requires approval)
- ✅ Record bills & invoices
- ✅ Process payments
- ✅ Bank reconciliation
- ✅ View basic reports
- ❌ Cannot close periods
- ❌ Cannot modify chart of accounts
- ❌ Cannot view payroll

#### 5. Manager
**Description:** Departmental oversight
**Permissions:**
- ✅ View department reports
- ✅ Approve department expenses
- ✅ Create purchase requisitions
- ✅ View budgets
- ❌ Cannot access other departments
- ❌ Cannot modify books

#### 6. Viewer
**Description:** Read-only access
**Permissions:**
- ✅ View reports (based on restrictions)
- ✅ Export allowed reports
- ❌ Cannot create/modify anything

### Custom Permissions Matrix

```typescript
interface Permissions {
  // Users & Settings
  manage_users: boolean;
  manage_billing: boolean;
  manage_integrations: boolean;

  // Entities & Structure
  create_entities: boolean;
  manage_chart_of_accounts: boolean;
  manage_departments: boolean;

  // Transactions
  create_transactions: boolean;
  approve_transactions: boolean;
  delete_transactions: boolean;
  void_transactions: boolean;

  // Banking
  connect_bank_accounts: boolean;
  reconcile_accounts: boolean;

  // AR/AP
  create_invoices: boolean;
  record_payments: boolean;
  create_bills: boolean;
  approve_bills: boolean;

  // Reporting
  view_reports: string[]; // array of allowed report types
  export_data: boolean;
  view_audit_trail: boolean;

  // Period Close
  close_periods: boolean;

  // Payroll
  view_payroll: boolean;
  process_payroll: boolean;

  // Advanced
  api_access: boolean;
  bulk_import: boolean;
  custom_fields: boolean;
}
```

---

## 🏭 Industry Templates

### 1. Government Contractor (DCAA Compliant)
**Features:**
- Pre-configured chart of accounts (direct/indirect costs)
- DCAA-compliant timekeeping
- Per-diem rate tables (GSA)
- Contract tracking
- Allowable/unallowable cost separation
- Indirect rate calculations
- Incurred cost submissions
- FAR compliance checks

**Pre-configured accounts:**
- 6000s: Direct Labor
- 6100s: Direct Materials
- 6200s: Other Direct Costs
- 7000s: Indirect Costs (Fringe, Overhead, G&A)

**Workflows:**
- Weekly timesheet approval
- Receipt validation ($75 threshold)
- Travel expense validation (per-diem)
- Unallowable cost flagging

---

### 2. Veteran-Owned Business
**Features:**
- VA benefits tracking
- Veteran hiring tax credits (WOTC)
- Service-disabled veteran designation
- VetBiz certification tracking
- SBA 8(a) compliance
- VA contract tracking
- Veteran employee management

**Special accounts:**
- VA Benefits Received
- WOTC Tax Credits
- SBA Loan Tracking

**Reports:**
- Veteran employment report
- VA contract revenue
- SDVOSB certification status

---

### 3. Law Enforcement
**Features:**
- Grant tracking (federal, state, local)
- Asset forfeiture accounting
- Evidence custody tracking
- Uniform/equipment inventory
- Vehicle fleet management
- Training budget tracking
- Overtime tracking

**Pre-configured accounts:**
- Grant Revenue (by source)
- Asset Forfeiture Funds
- Equipment & Uniforms
- Vehicle Maintenance
- Training Expenses

**Compliance:**
- Grant expenditure reporting
- Asset forfeiture documentation
- Budget variance alerts

---

### 4. Healthcare (HIPAA-Ready)
**Features:**
- Insurance billing tracking
- Patient payment management
- Medical supplies inventory
- HIPAA-compliant audit trails
- Provider revenue tracking
- Insurance A/R aging
- Credentialing tracking

**Pre-configured accounts:**
- Insurance Receivables (by carrier)
- Patient Receivables
- Medical Supplies
- Provider Compensation
- Malpractice Insurance

**Compliance:**
- PHI access logging
- HIPAA audit trails
- Breach notification ready

---

### 5. Real Estate
**Features:**
- Property tracking (by unit/building)
- Tenant rent tracking
- Security deposit management
- Property maintenance
- Mortgage/loan tracking
- 1099 for contractors
- Rental income Schedule E

**Pre-configured accounts:**
- Rental Income (by property)
- Security Deposits Liability
- Property Maintenance
- Mortgage Interest
- Property Tax
- Depreciation (by property)

**Reports:**
- Rent roll
- Property P&L
- Lease expiration tracker
- Maintenance log

---

### 6. E-commerce
**Features:**
- Sales channel tracking (Shopify, Amazon, website)
- COGS & inventory
- Shipping & fulfillment costs
- Payment processor fees (Stripe, PayPal)
- Returns & refunds
- Sales tax tracking (by state)
- Marketplace fees

**Pre-configured accounts:**
- Sales by Channel
- COGS
- Shipping Revenue
- Shipping Expense
- Payment Processing Fees
- Marketplace Fees (Amazon, eBay)

**Integrations:**
- Shopify
- Amazon Seller Central
- Stripe
- PayPal

---

### 7. Professional Services (Consulting, Legal, etc.)
**Features:**
- Time tracking & billing
- Client project tracking
- Retainer management
- Billable vs non-billable hours
- Client trust accounts (for lawyers)
- Utilization reports
- Realization reports

**Pre-configured accounts:**
- Client Retainers (liability)
- Unbilled Revenue
- Work in Progress
- Client Trust Account

**Reports:**
- Billable hours by client
- Utilization rate
- Realization rate
- WIP aging

---

### 8. Construction
**Features:**
- Job costing (by project)
- Change order tracking
- AIA billing (progress billing)
- Retention tracking
- Subcontractor management
- Materials tracking
- Equipment rental

**Pre-configured accounts:**
- Costs by Job
- Customer Retainage Receivable
- Vendor Retainage Payable
- Equipment Rental
- Subcontractor Costs

**Reports:**
- Job profitability
- WIP report
- Over/under billing

---

### 9. Retail
**Features:**
- Point of sale integration
- Inventory management (FIFO, LIFO, Average)
- Multi-location tracking
- Sales by location
- Shrinkage tracking
- Sales tax by jurisdiction

**Pre-configured accounts:**
- Sales by Location
- COGS
- Inventory
- Shrinkage
- Sales Tax Payable (by state)

**Integrations:**
- Square
- Clover
- Shopify POS

---

## 🚀 Scalability Features

### Multi-Currency Support
```sql
CREATE TABLE currencies (
  code TEXT PRIMARY KEY, -- USD, EUR, GBP, etc.
  name TEXT NOT NULL,
  symbol TEXT NOT NULL,
  decimal_places INTEGER DEFAULT 2,
  is_active BOOLEAN DEFAULT TRUE
);

CREATE TABLE exchange_rates (
  id UUID PRIMARY KEY,
  from_currency TEXT REFERENCES currencies(code),
  to_currency TEXT REFERENCES currencies(code),
  rate DECIMAL(20,10) NOT NULL,
  effective_date DATE NOT NULL,

  UNIQUE(from_currency, to_currency, effective_date)
);

-- Add to accounts, transactions
ALTER TABLE accounts ADD COLUMN currency TEXT DEFAULT 'USD' REFERENCES currencies(code);
ALTER TABLE journal_entry_lines ADD COLUMN currency TEXT DEFAULT 'USD';
ALTER TABLE journal_entry_lines ADD COLUMN exchange_rate DECIMAL(20,10);
ALTER TABLE journal_entry_lines ADD COLUMN base_currency_amount DECIMAL(15,2);
```

### Department/Class Tracking
```sql
-- Already defined in dimensions table above
-- Can track unlimited dimensions:
-- - Department (Sales, Marketing, Engineering)
-- - Class (Product Line A, Product Line B)
-- - Location (NY Office, LA Office)
-- - Project (Project Alpha, Project Beta)
-- - Custom (any user-defined dimension)

-- Applied to transactions
CREATE TABLE transaction_dimensions (
  id UUID PRIMARY KEY,
  transaction_id UUID, -- could be journal_entry_id, invoice_id, etc.
  transaction_type TEXT, -- journal_entry, invoice, bill, etc.
  dimension_id UUID REFERENCES dimensions(id),

  UNIQUE(transaction_id, transaction_type, dimension_id)
);
```

### Custom Fields
```sql
CREATE TABLE custom_fields (
  id UUID PRIMARY KEY,
  organization_id UUID REFERENCES organizations(id),
  entity_type TEXT NOT NULL, -- customer, vendor, invoice, transaction, etc.
  field_name TEXT NOT NULL,
  field_type TEXT NOT NULL, -- text, number, date, dropdown, checkbox
  field_options JSONB, -- for dropdown: ["Option 1", "Option 2"]
  is_required BOOLEAN DEFAULT FALSE,
  display_order INTEGER,

  UNIQUE(organization_id, entity_type, field_name)
);

CREATE TABLE custom_field_values (
  id UUID PRIMARY KEY,
  custom_field_id UUID REFERENCES custom_fields(id),
  record_id UUID NOT NULL, -- ID of the customer, invoice, etc.
  value TEXT,

  UNIQUE(custom_field_id, record_id)
);
```

### Approval Workflows
```sql
CREATE TABLE approval_rules (
  id UUID PRIMARY KEY,
  organization_id UUID REFERENCES organizations(id),
  entity_id UUID REFERENCES entities(id),

  transaction_type TEXT NOT NULL, -- bill, expense, journal_entry, etc.
  condition JSONB, -- {"amount_over": 1000, "department": "Marketing"}

  requires_approval_from TEXT, -- role or specific user_id
  approval_order INTEGER, -- for multi-level approvals

  is_active BOOLEAN DEFAULT TRUE
);

CREATE TABLE approvals (
  id UUID PRIMARY KEY,
  transaction_id UUID NOT NULL,
  transaction_type TEXT NOT NULL,

  required_approver_id UUID REFERENCES users(id),
  approved_by UUID REFERENCES users(id),
  approved_at TIMESTAMPTZ,

  status TEXT DEFAULT 'pending', -- pending, approved, rejected
  notes TEXT
);
```

---

## 📱 API Access Tiers

### Free/Individual: No API
### Freelancer: No API
### Small Business: Basic API
- 1,000 requests/day
- Read-only access
- Webhooks (5 max)

### Professional: Advanced API
- 10,000 requests/day
- Read + Write access
- Webhooks (50 max)
- Custom integrations

### Enterprise: Unlimited API
- Unlimited requests
- Full CRUD access
- Custom webhooks
- Dedicated API endpoints
- GraphQL support
- Batch operations

---

## 🎨 White-Label Options (Enterprise)

```sql
-- In organizations table branding JSONB:
{
  "logo_url": "https://...",
  "favicon_url": "https://...",
  "primary_color": "#1E40AF",
  "secondary_color": "#3B82F6",
  "company_name": "Custom Accounting Co.",
  "custom_domain": "accounting.customco.com",
  "email_from_name": "Custom Accounting",
  "email_from_address": "noreply@customco.com",
  "support_email": "support@customco.com",
  "support_url": "https://customco.com/support",
  "terms_url": "https://customco.com/terms",
  "privacy_url": "https://customco.com/privacy"
}
```

---

## 🔄 Migration Path

Users can seamlessly upgrade tiers:

1. **Individual → Freelancer**
   - Enable invoicing
   - Import customers
   - Upgrade chart of accounts

2. **Freelancer → Small Business**
   - Add team members
   - Enable full accounting
   - Set up departments

3. **Small Business → Professional**
   - Add entities
   - Enable advanced workflows
   - Set up multi-currency

4. **Professional → Enterprise**
   - Unlimited users
   - Custom integrations
   - White-label setup

**No data migration needed** - all features are additive!

---

## 💡 Smart Defaults by Tier

When user signs up, system auto-configures based on tier + industry:

**Individual + No Industry:**
- Basic expense categories
- Simple reports
- Mobile-first interface

**Freelancer + Veteran:**
- Schedule C chart of accounts
- VA benefits tracking enabled
- Veteran tax credits enabled
- Mileage tracking enabled

**Small Business + Government Contractor:**
- DCAA-compliant chart of accounts
- Timekeeping enabled
- Per-diem tables loaded
- Travel expense validation enabled
- Contract tracking enabled

**Enterprise + Multi-State Retail:**
- Multi-entity setup
- Multi-currency enabled
- Sales tax by jurisdiction
- Inventory tracking
- POS integration ready

---

## 📊 Feature Flag Management

```typescript
interface FeatureFlags {
  // Core features
  invoicing: boolean;
  bill_tracking: boolean;
  full_accounting: boolean;
  payroll_integration: boolean;

  // Multi-user
  multi_user: boolean;
  max_users: number;
  role_based_access: boolean;
  approval_workflows: boolean;

  // Multi-entity
  multi_entity: boolean;
  max_entities: number;
  consolidated_reporting: boolean;

  // Advanced
  multi_currency: boolean;
  department_tracking: boolean;
  custom_fields: boolean;
  api_access: boolean;
  white_label: boolean;

  // Industry-specific
  dcaa_compliance: boolean;
  hipaa_compliance: boolean;
  va_benefits_tracking: boolean;
  grant_tracking: boolean;

  // Integrations
  bank_connections: number; // max bank accounts
  integrations_enabled: string[]; // ["shopify", "stripe", etc.]

  // Storage & Limits
  max_transactions_per_month: number;
  data_retention_years: number;
  file_storage_gb: number;
}
```

---

## 🎯 Next Steps for Implementation

1. **Phase 1: Multi-Tenancy Foundation** (Week 1-2)
   - Create organizations, users, entities tables
   - Implement Row-Level Security (RLS)
   - Add organization context to all queries
   - Create migration scripts for existing data

2. **Phase 2: RBAC System** (Week 3)
   - Implement roles & permissions
   - Create permission middleware
   - Add user invitation system
   - Build team management UI

3. **Phase 3: Feature Flags** (Week 4)
   - Implement tier-based feature detection
   - Create feature flag middleware
   - Build subscription management
   - Add usage tracking

4. **Phase 4: Industry Templates** (Week 5-6)
   - Build template system
   - Create DCAA template (priority)
   - Create Veteran template
   - Create Law Enforcement template

5. **Phase 5: Advanced Features** (Week 7-8)
   - Multi-currency support
   - Department tracking
   - Custom fields
   - Approval workflows

---

*This architecture supports growth from 1 user to 10,000+ users without code changes!*
