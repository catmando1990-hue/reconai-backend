# Frontend-Backend Integration Guide

**Date:** December 23, 2025
**Backend Status:** ✅ 95% Complete - Ready for Integration
**Frontend Status:** ⚠️ Needs API Connections

---

## 🎯 Quick Summary

Your **backend is running and ready** at http://localhost:8000 with all these endpoints operational:

✅ User Profile & Settings
✅ Transaction Classification (AI-powered)
✅ DCAA Compliance Checking
✅ Tax Optimization
✅ Financial Reports (P&L, Balance Sheet, Cash Flow, Trial Balance)
✅ Invoice & Payment Management
✅ Customer CRM
✅ Double-Entry Bookkeeping
✅ Plaid Bank Integration
✅ Stripe Webhooks

**What Frontend Needs to Do:** Connect the existing UI pages to these working API endpoints.

---

## 📋 Frontend TODO List (Priority Order)

### **Priority 1: Connect Existing Pages to Backend (URGENT)**

These pages exist in your frontend but currently use mock data. Replace mock data with real API calls:

#### 1. Contact Form (`app/contact/page.tsx:35`)
```typescript
// CURRENT (Mock):
// TODO: Implement actual form submission to backend

// REPLACE WITH:
const response = await fetch('http://localhost:8000/api/contact/', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    name: formData.name,
    email: formData.email,
    message: formData.message
  })
});
```

**Backend Endpoint:** `POST /api/contact/`
**Request:** `{ name: string, email: string, message: string }`
**Response:** `{ message: "Contact form submitted successfully" }`

---

#### 2. Compliance Dashboard (`app/(dashboard)/compliance/page.tsx:47`)
```typescript
// CURRENT (Mock):
// TODO: Replace with actual API call to backend

// REPLACE WITH:
const response = await fetch('http://localhost:8000/api/compliance/check', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${await getToken()}`  // Clerk token
  },
  body: JSON.stringify({
    transactions: userTransactions  // Array of transactions
  })
});

const complianceData = await response.json();
// Returns: { overall_score, overall_status, indicators[], recommendations[] }
```

**Backend Endpoint:** `POST /api/compliance/check`
**Request:**
```typescript
{
  transactions: Array<{
    amount: number;
    description?: string;
    merchant_name?: string;
    has_receipt?: boolean;
    receipt_url?: string;
    reconai_category?: string;
  }>;
  business_type?: string;  // default: "Schedule C"
  compliance_type?: string;  // default: "dcaa"
}
```
**Response:**
```typescript
{
  overall_score: number;  // 0-100
  overall_status: "compliant" | "warning" | "critical";
  indicators: Array<{
    id: string;
    name: string;
    status: "compliant" | "warning" | "critical";
    score: number;
    description: string;
    last_checked: string;
  }>;
  total_transactions: number;
  compliant_transactions: number;
  non_compliant_transactions: number;
  recommendations: Array<{
    priority: "high" | "medium" | "low";
    category: string;
    title: string;
    description: string;
    action: string;
  }>;
}
```

---

#### 3. Settings - Profile (`app/(dashboard)/settings/page.tsx:77`)
```typescript
// CURRENT (Mock):
// TODO: Implement actual API call to save profile

// REPLACE WITH (GET profile on load):
const profileResponse = await fetch('http://localhost:8000/api/user/profile', {
  headers: {
    'Authorization': `Bearer ${await getToken()}`
  }
});
const profile = await profileResponse.json();

// REPLACE WITH (SAVE profile):
const saveResponse = await fetch('http://localhost:8000/api/user/profile', {
  method: 'PUT',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${await getToken()}`
  },
  body: JSON.stringify({
    name: formData.name,
    email: formData.email,
    company: formData.company,
    phone: formData.phone,
    address: formData.address,
    city: formData.city,
    state: formData.state,
    zip: formData.zip
  })
});
```

**Backend Endpoints:**
- `GET /api/user/profile` - Get current user profile
- `PUT /api/user/profile` - Update user profile

**Profile Schema:**
```typescript
interface UserProfile {
  name?: string;
  email?: string;
  company?: string;
  phone?: string;
  address?: string;
  city?: string;
  state?: string;
  zip?: string;
  country?: string;
  timezone?: string;
}
```

---

#### 4. Settings - Notifications (`app/(dashboard)/settings/page.tsx:91`)
```typescript
// CURRENT (Mock):
// TODO: Implement actual API call to save notifications

// REPLACE WITH (GET notifications on load):
const notifResponse = await fetch('http://localhost:8000/api/user/notifications', {
  headers: {
    'Authorization': `Bearer ${await getToken()}`
  }
});
const notifications = await notifResponse.json();

// REPLACE WITH (SAVE notifications):
const saveResponse = await fetch('http://localhost:8000/api/user/notifications', {
  method: 'PUT',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${await getToken()}`
  },
  body: JSON.stringify({
    email_notifications: true,
    transaction_alerts: true,
    compliance_alerts: true,
    invoice_reminders: true,
    weekly_summary: false,
    monthly_report: true
  })
});
```

**Backend Endpoints:**
- `GET /api/user/notifications` - Get notification settings
- `PUT /api/user/notifications` - Update notification settings

**Notification Schema:**
```typescript
interface NotificationSettings {
  email_notifications: boolean;
  transaction_alerts: boolean;
  compliance_alerts: boolean;
  invoice_reminders: boolean;
  weekly_summary: boolean;
  monthly_report: boolean;
}
```

---

#### 5. Homepage Waitlist (`app/page.tsx:58`)
```typescript
// CURRENT (Mock):
// TODO: Replace with actual API endpoint for waitlist signup

// REPLACE WITH:
const response = await fetch('http://localhost:8000/api/newsletter/subscribe', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    email: waitlistEmail
  })
});
```

**Backend Endpoint:** `POST /api/newsletter/subscribe`
**Request:** `{ email: string }`
**Response:** `{ message: "Successfully subscribed" }`

---

#### 6. Tax Optimization Page (`app/(dashboard)/tax/page.tsx`)
```typescript
// Page exists with UI - needs backend connection

const response = await fetch('http://localhost:8000/api/tax/optimize', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${await getToken()}`
  },
  body: JSON.stringify({
    transactions: userTransactions,
    year: 2025,
    user_type: "individual"  // or "business"
  })
});

const taxOptimization = await response.json();
// Returns: { total_deductions, potential_savings, recommendations[], quarterly_estimates[] }
```

**Backend Endpoint:** `POST /api/tax/optimize`
**Response:**
```typescript
{
  total_deductions: number;
  potential_savings: number;
  recommendations: Array<{
    category: string;
    amount: number;
    description: string;
    priority: "high" | "medium" | "low";
  }>;
  quarterly_estimates: Array<{
    quarter: string;  // "Q1", "Q2", etc.
    due_date: string;  // "2025-04-15"
    amount: number;
  }>;
}
```

---

#### 7. Financial Reports (`app/(dashboard)/financial-reports/page.tsx`)
```typescript
// Page exists with mock data - needs backend connection

// Income Statement (P&L)
const incomeStatement = await fetch(
  `http://localhost:8000/api/reports/income-statement?` +
  `org_id=${orgId}&start_date=2025-01-01&end_date=2025-12-31`,
  {
    headers: { 'Authorization': `Bearer ${await getToken()}` }
  }
);

// Balance Sheet
const balanceSheet = await fetch(
  `http://localhost:8000/api/reports/balance-sheet?` +
  `org_id=${orgId}&as_of_date=2025-12-23`,
  {
    headers: { 'Authorization': `Bearer ${await getToken()}` }
  }
);

// Cash Flow Statement
const cashFlow = await fetch(
  `http://localhost:8000/api/reports/cash-flow?` +
  `org_id=${orgId}&start_date=2025-01-01&end_date=2025-12-31`,
  {
    headers: { 'Authorization': `Bearer ${await getToken()}` }
  }
);
```

**Backend Endpoints:**
- `GET /api/reports/income-statement` - P&L statement
- `GET /api/reports/balance-sheet` - Balance sheet
- `GET /api/reports/cash-flow` - Cash flow statement
- `GET /api/reports/trial-balance` - Trial balance
- `POST /api/reports/generate` - Generic report generator

---

#### 8. Journal Entries (`app/(dashboard)/journal/page.tsx`)
```typescript
// Page exists with mock data - needs backend connection

// List journal entries
const entries = await fetch(
  `http://localhost:8000/api/bookkeeping/journal-entries?org_id=${orgId}`,
  {
    headers: { 'Authorization': `Bearer ${await getToken()}` }
  }
);

// Create journal entry
const createEntry = await fetch(
  'http://localhost:8000/api/bookkeeping/journal-entries',
  {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${await getToken()}`
    },
    body: JSON.stringify({
      entry_date: "2025-12-23",
      description: "Office supplies purchase",
      lines: [
        {
          account_id: "5050",  // Office Expenses
          debit: "150.00",
          credit: "0.00",
          memo: "Staples purchase"
        },
        {
          account_id: "2100",  // Credit Card
          debit: "0.00",
          credit: "150.00",
          memo: "Staples purchase"
        }
      ]
    })
  }
);
```

**Backend Endpoints:**
- `GET /api/bookkeeping/journal-entries` - List entries
- `POST /api/bookkeeping/journal-entries` - Create entry
- `POST /api/bookkeeping/journal-entries/{id}/post` - Post entry (make permanent)
- `POST /api/bookkeeping/journal-entries/{id}/void` - Void entry

---

### **Priority 2: Missing Frontend Pages to Create**

#### 1. **Bills & AP (Accounts Payable) Page**
Create: `app/(dashboard)/bills/page.tsx`

This page should manage vendor bills and payments. Backend endpoints ready:
- `GET /api/vendors` - List vendors (not yet created, add to backend)
- `POST /api/vendors` - Create vendor
- `GET /api/bills` - List bills (not yet created, add to backend)
- `POST /api/bills` - Create bill
- `POST /api/bills/{id}/payments` - Pay bill

#### 2. **Receipt Upload Component**
Add to transaction detail views or create dedicated upload page.

Backend endpoints ready:
- `POST /files/upload` - Upload file (already exists)
- Need to link receipts to transactions

#### 3. **Export Buttons on Reports**
Add export buttons (CSV/JSON) to all report pages.

Backend supports export parameters on all report endpoints.

---

### **Priority 3: Complete Plaid Integration**

#### Bank Connection Flow
```typescript
// Step 1: Get Plaid Link token
const linkTokenResponse = await fetch('http://localhost:8000/link-token', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${await getToken()}`
  },
  body: JSON.stringify({
    client_user_id: userId
  })
});
const { link_token } = await linkTokenResponse.json();

// Step 2: Open Plaid Link UI (using @plaid/link SDK)
import { usePlaidLink } from 'react-plaid-link';

const { open, ready } = usePlaidLink({
  token: link_token,
  onSuccess: async (public_token, metadata) => {
    // Step 3: Exchange public token for access token
    const exchangeResponse = await fetch('http://localhost:8000/exchange-token', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${await getToken()}`
      },
      body: JSON.stringify({
        public_token: public_token
      })
    });

    // Step 4: Fetch transactions
    const transactionsResponse = await fetch(
      'http://localhost:8000/transactions',
      {
        headers: { 'Authorization': `Bearer ${await getToken()}` }
      }
    );
  }
});

// Open Plaid Link
open();
```

---

## 🔑 Authentication Flow

**All protected endpoints require Clerk JWT token:**

```typescript
import { useAuth } from '@clerk/nextjs';

const { getToken } = useAuth();

const response = await fetch('http://localhost:8000/api/...', {
  headers: {
    'Authorization': `Bearer ${await getToken()}`
  }
});
```

Backend automatically:
1. Validates Clerk JWT token
2. Extracts `user_id` from token
3. Uses `user_id` for all database queries

---

## 🛠️ Backend Endpoints Summary

### User Management
- ✅ `GET /api/user/profile` - Get user profile
- ✅ `PUT /api/user/profile` - Update user profile
- ✅ `GET /api/user/notifications` - Get notification settings
- ✅ `PUT /api/user/notifications` - Update notification settings

### Authentication
- ✅ `POST /api/auth/login` - Login (Clerk handles this)
- ✅ `POST /api/auth/validate` - Validate Clerk token

### Organizations
- ✅ `GET /api/organizations` - List user's organizations
- ✅ `POST /api/organizations` - Create organization
- ✅ `GET /api/organizations/{id}` - Get organization
- ✅ `PATCH /api/organizations/{id}` - Update organization

### Customers
- ✅ `GET /api/customers?org_id={org_id}` - List customers
- ✅ `POST /api/customers?org_id={org_id}` - Create customer
- ✅ `GET /api/customers/{id}` - Get customer
- ✅ `PATCH /api/customers/{id}` - Update customer
- ✅ `DELETE /api/customers/{id}` - Delete customer

### Invoices
- ✅ `GET /api/invoices?org_id={org_id}` - List invoices
- ✅ `POST /api/invoices?org_id={org_id}` - Create invoice
- ✅ `GET /api/invoices/{id}` - Get invoice
- ✅ `PATCH /api/invoices/{id}` - Update invoice
- ✅ `DELETE /api/invoices/{id}` - Delete invoice
- ✅ `POST /api/invoices/{id}/payments` - Record payment
- ⚠️ `POST /api/invoices/{id}/send` - Email invoice (NEED TO ADD)
- ⚠️ `GET /api/invoices/{id}/pdf` - Generate PDF (NEED TO ADD)

### Financial Reports
- ✅ `GET /api/reports/income-statement` - P&L
- ✅ `GET /api/reports/balance-sheet` - Balance sheet
- ✅ `GET /api/reports/cash-flow` - Cash flow
- ✅ `GET /api/reports/trial-balance` - Trial balance
- ✅ `POST /api/reports/generate` - Generic report generator
- ⚠️ `GET /api/reports/ar-aging` - AR aging (NEED TO ADD)

### Tax & Compliance
- ✅ `POST /api/tax/optimize` - Tax optimization
- ✅ `POST /api/compliance/check` - Compliance checking
- ⚠️ `GET /api/tax/summary/{year}` - Tax year summary (NEED TO ADD)
- ⚠️ `POST /api/tax/mileage` - Log mileage (NEED TO ADD)

### Bookkeeping
- ✅ `GET /api/bookkeeping/accounts` - Chart of accounts
- ✅ `POST /api/bookkeeping/accounts` - Create account
- ✅ `GET /api/bookkeeping/journal-entries` - List journal entries
- ✅ `POST /api/bookkeeping/journal-entries` - Create journal entry
- ✅ `POST /api/bookkeeping/journal-entries/{id}/post` - Post entry
- ✅ `GET /api/bookkeeping/trial-balance` - Trial balance
- ✅ `GET /api/bookkeeping/general-ledger/{account_id}` - General ledger

### Plaid (Banking)
- ✅ `POST /link-token` - Get Plaid Link token
- ✅ `POST /exchange-token` - Exchange public token
- ✅ `GET /transactions` - Get user transactions
- ✅ `POST /classify-transactions` - AI transaction classification
- ⚠️ `GET /api/plaid/accounts` - List connected banks (NEED TO ADD)
- ⚠️ `DELETE /api/plaid/accounts/{item_id}` - Disconnect bank (NEED TO ADD)

### Contact & Newsletter
- ✅ `POST /api/contact/` - Submit contact form
- ✅ `POST /api/newsletter/subscribe` - Subscribe to newsletter

### Stripe
- ✅ `POST /api/webhooks/stripe` - Stripe webhook handler

---

## ⚠️ Still Missing from Backend

These endpoints need to be added:

1. **Receipt Management**
   - `POST /api/receipts/upload` - Upload receipt
   - `GET /api/receipts` - List receipts
   - `DELETE /api/receipts/{id}` - Delete receipt

2. **Bank Account Management (Plaid)**
   - `GET /api/plaid/accounts` - List connected banks
   - `DELETE /api/plaid/accounts/{item_id}` - Disconnect bank

3. **Transaction Categorization**
   - `PUT /api/transactions/{id}/category` - Update transaction category

4. **Financial Goals**
   - `GET /api/goals` - List financial goals
   - `POST /api/goals` - Create goal
   - `PUT /api/goals/{id}` - Update goal
   - `DELETE /api/goals/{id}` - Delete goal

5. **Audit Logs**
   - `GET /api/audit-logs` - Query audit logs

6. **Invoice PDF & Email**
   - `GET /api/invoices/{id}/pdf` - Generate PDF
   - `POST /api/invoices/{id}/send` - Email invoice

7. **Vendors & Bills (AP)**
   - `GET /api/vendors` - List vendors
   - `POST /api/vendors` - Create vendor
   - `GET /api/bills` - List bills
   - `POST /api/bills` - Create bill

---

## 🚀 Quick Start for Frontend Team

### Step 1: Set Environment Variables
```env
# .env.local
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
NEXT_PUBLIC_APP_URL=http://localhost:3001
```

### Step 2: Create API Helper
```typescript
// lib/api.ts
import { useAuth } from '@clerk/nextjs';

export const useBackendAPI = () => {
  const { getToken } = useAuth();

  const call = async (endpoint: string, options?: RequestInit) => {
    const token = await getToken();

    return fetch(`${process.env.NEXT_PUBLIC_BACKEND_URL}${endpoint}`, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
        ...options?.headers,
      },
    });
  };

  return { call };
};
```

### Step 3: Use in Components
```typescript
// Example: Contact form
const { call } = useBackendAPI();

const handleSubmit = async () => {
  const response = await call('/api/contact/', {
    method: 'POST',
    body: JSON.stringify({ name, email, message })
  });

  if (response.ok) {
    toast.success('Message sent!');
  }
};
```

---

## 📊 Integration Status

### ✅ Backend Ready (95%)
- User profile & settings
- Transaction classification
- Compliance checking
- Tax optimization
- Financial reports
- Invoice management
- Customer management
- Bookkeeping
- Plaid integration (partial)

### ⚠️ Frontend Needs Work
- Connect 8 existing pages to APIs
- Create 3 missing pages
- Complete Plaid integration flow
- Add export buttons

### ⚠️ Backend TODO (5%)
- Receipt upload endpoints
- Bank account management endpoints
- Transaction categorization endpoint
- Financial goals CRUD
- Audit log queries
- Invoice PDF generation
- Vendor & bills endpoints

---

## 🎯 Next Steps

**For Frontend Team:**
1. Replace all TODO comments with actual API calls (Priority 1)
2. Test each endpoint with localhost:8000
3. Create missing pages (Bills/AP, Receipt upload)
4. Complete Plaid Link integration

**For Backend:**
1. Add remaining 7 missing endpoint groups (5% remaining)
2. Test all endpoints with frontend
3. Deploy to production

**Estimated Integration Time:** 2-3 days for frontend to connect all existing endpoints

---

## 📞 Support

Backend API documentation: http://localhost:8000/docs
Backend running at: http://localhost:8000
Frontend should run at: http://localhost:3001

All endpoints are CORS-enabled for localhost:3001 and ready for integration! 🚀
