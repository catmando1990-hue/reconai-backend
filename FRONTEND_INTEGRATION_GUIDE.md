# Frontend Integration Guide

**Date:** December 22, 2025
**Status:** ✅ Ready for Integration

---

## Quick Start

Your backend is now **100% ready** for frontend integration. All endpoints are properly registered and match your frontend's expectations.

---

## Backend Setup

### 1. Start the Backend

```bash
cd C:\reconai-backend
uvicorn app.main:app --reload
```

The backend will be available at: **http://localhost:8000**

### 2. Verify All Endpoints

Visit: **http://localhost:8000/docs**

You should see all these API endpoints:

- ✅ `/api/auth` - Authentication (Clerk integration)
- ✅ `/api/organizations` - Organization management
- ✅ `/api/entities` - Multi-entity support
- ✅ `/api/customers` - Customer CRM
- ✅ `/api/invoices` - Invoice management
- ✅ `/api/reports` - Financial reports
- ✅ `/api/tax/optimize` - Tax optimization (NEW)
- ✅ `/api/compliance/check` - DCAA compliance (NEW)
- ✅ `/api/webhooks/stripe` - Stripe webhooks
- ✅ `/classify-transactions` - AI classification

---

## Frontend Environment Variables

Update your `.env.local` file in the frontend:

```env
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
NEXT_PUBLIC_APP_URL=http://localhost:3000
```

For production:
```env
NEXT_PUBLIC_BACKEND_URL=https://reconai-backend.onrender.com
```

---

## API Endpoints Ready for Frontend

### 1. Customer Management

**Endpoint:** `GET /api/customers?org_id={org_id}`

**Response:**
```typescript
interface Customer {
  id: string;
  name: string;
  email: string;
  phone: string;
  company_name: string;
  address_line1: string;
  city: string;
  state: string;
  zip: string;
  outstanding_balance: number;
  total_invoiced: number;      // ✅ NEW - Total amount invoiced
  total_paid: number;           // ✅ NEW - Total amount paid
  active_invoices: number;      // ✅ NEW - Count of active invoices
  payment_terms: number;
  is_active: boolean;
}
```

**Frontend Usage:**
```typescript
const response = await fetch(`${BACKEND_URL}/api/customers?org_id=${orgId}`, {
  headers: {
    'Authorization': `Bearer ${clerkToken}`
  }
});
const customers: Customer[] = await response.json();
```

---

### 2. Tax Optimization (NEW)

**Endpoint:** `POST /api/tax/optimize`

**Request:**
```typescript
interface TaxOptimizationRequest {
  transactions: Transaction[];
  year?: number;
  user_type?: string;
}
```

**Response:**
```typescript
interface TaxOptimizationResponse {
  total_deductions: number;
  potential_savings: number;
  recommendations: Array<{
    category: string;
    amount: number;
    description: string;
    priority: 'high' | 'medium' | 'low';
  }>;
  quarterly_estimates: Array<{
    quarter: string;
    due_date: string;
    amount: number;
  }>;
}
```

**Frontend Usage:**
```typescript
const response = await fetch(`${BACKEND_URL}/api/tax/optimize`, {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${clerkToken}`
  },
  body: JSON.stringify({
    transactions: transactions,
    year: 2025
  })
});
const optimization: TaxOptimizationResponse = await response.json();
```

---

### 3. Compliance Checking (NEW)

**Endpoint:** `POST /api/compliance/check`

**Request:**
```typescript
interface ComplianceCheckRequest {
  transactions: Transaction[];
  business_type?: string;
  compliance_type?: string;
}
```

**Response:**
```typescript
interface ComplianceIndicator {
  id: string;
  name: string;
  status: 'compliant' | 'warning' | 'critical';
  score: number;
  description: string;
  last_checked: string;
}

interface ComplianceCheckResponse {
  overall_score: number;
  overall_status: 'compliant' | 'warning' | 'critical';
  indicators: ComplianceIndicator[];
  total_transactions: number;
  compliant_transactions: number;
  non_compliant_transactions: number;
  recommendations: Array<{
    priority: 'high' | 'medium' | 'low';
    category: string;
    title: string;
    description: string;
    action: string;
  }>;
}
```

**Frontend Usage:**
```typescript
const response = await fetch(`${BACKEND_URL}/api/compliance/check`, {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${clerkToken}`
  },
  body: JSON.stringify({
    transactions: transactions,
    compliance_type: 'dcaa'
  })
});
const compliance: ComplianceCheckResponse = await response.json();
```

---

### 4. Generic Report Generation (NEW)

**Endpoint:** `POST /api/reports/generate`

**Parameters:**
```typescript
interface ReportGenerationParams {
  org_id: string;
  report_type: 'income-statement' | 'balance-sheet' | 'trial-balance' | 'cash-flow' | 'summary';
  start_date?: string;  // Required for income-statement, cash-flow
  end_date?: string;    // Required for income-statement, cash-flow
  as_of_date?: string;  // Required for balance-sheet, trial-balance
  entity_id?: string;
}
```

**Frontend Usage:**
```typescript
// Income Statement
const response = await fetch(
  `${BACKEND_URL}/api/reports/generate?` +
  `org_id=${orgId}&` +
  `report_type=income-statement&` +
  `start_date=2025-01-01&` +
  `end_date=2025-12-31`,
  {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${clerkToken}` }
  }
);
const incomeStatement = await response.json();

// Financial Summary
const summaryResponse = await fetch(
  `${BACKEND_URL}/api/reports/generate?` +
  `org_id=${orgId}&` +
  `report_type=summary&` +
  `as_of_date=2025-12-22`,
  {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${clerkToken}` }
  }
);
const summary = await response.json();
```

---

### 5. Invoice Management

**List Invoices:** `GET /api/invoices?org_id={org_id}`

**Create Invoice:** `POST /api/invoices?org_id={org_id}`

**Request:**
```typescript
interface CreateInvoiceRequest {
  customer_id: string;
  invoice_date: string;
  due_date: string;
  line_items: Array<{
    description: string;
    quantity: number;
    unit_price: number;
    tax_rate?: number;
  }>;
  discount_amount?: number;
  shipping_amount?: number;
  notes?: string;
  terms?: string;
}
```

**Record Payment:** `POST /api/invoices/{invoice_id}/payments?org_id={org_id}`

**Request:**
```typescript
interface RecordPaymentRequest {
  amount: number;
  payment_date: string;
  payment_method: 'cash' | 'check' | 'credit_card' | 'bank_transfer' | 'other';
  reference_number?: string;
  notes?: string;
}
```

---

## Testing the Integration

### 1. Test Customer API

```bash
curl http://localhost:8000/api/customers?org_id=org-test
```

Should return customers with `total_invoiced`, `total_paid`, and `active_invoices` fields.

### 2. Test Tax Optimization

```bash
curl -X POST http://localhost:8000/api/tax/optimize \
  -H "Content-Type: application/json" \
  -d '{
    "transactions": [
      {"amount": -1500, "reconai_category": "Business - Software"},
      {"amount": -500, "reconai_category": "Business - Travel"}
    ],
    "year": 2025
  }'
```

Should return deductions and quarterly estimates.

### 3. Test Compliance Check

```bash
curl -X POST http://localhost:8000/api/compliance/check \
  -H "Content-Type: application/json" \
  -d '{
    "transactions": [
      {"amount": -150, "description": "Office supplies", "has_receipt": true},
      {"amount": -80, "description": "Lunch", "has_receipt": false}
    ]
  }'
```

Should return compliance indicators and recommendations.

### 4. Test Report Generation

```bash
curl -X POST "http://localhost:8000/api/reports/generate?org_id=org-test&report_type=summary&as_of_date=2025-12-22"
```

Should return financial summary with metrics.

---

## CORS Configuration

The backend is configured to accept requests from:

**Development:**
- `http://localhost:3000` (Next.js)
- `http://localhost:5173` (Vite)
- `http://127.0.0.1:3000`
- `http://127.0.0.1:5173`

**Production:**
- `https://reconai-frontend.vercel.app`
- `https://*.vercel.app` (all Vercel preview deployments)
- `https://reconai-frontend.onrender.com`

**Allowed Methods:** GET, POST, PUT, PATCH, DELETE, OPTIONS
**Credentials:** Enabled
**Headers:** All headers allowed

---

## TypeScript Type Definitions

You can use these TypeScript interfaces in your frontend:

```typescript
// Customer
interface Customer {
  id: string;
  organization_id: string;
  entity_id?: string;
  name: string;
  email?: string;
  phone?: string;
  company_name?: string;
  address_line1?: string;
  address_line2?: string;
  city?: string;
  state?: string;
  zip?: string;
  country: string;
  tax_id?: string;
  payment_terms: number;
  outstanding_balance: number;
  total_invoiced: number;
  total_paid: number;
  active_invoices: number;
  is_active: boolean;
  notes?: string;
  created_at: string;
  updated_at: string;
}

// Invoice
interface Invoice {
  id: string;
  organization_id: string;
  entity_id?: string;
  customer_id: string;
  customer_name: string;
  invoice_number: string;
  invoice_date: string;
  due_date: string;
  subtotal: number;
  tax_total: number;
  discount_amount: number;
  shipping_amount: number;
  total_amount: number;
  amount_paid: number;
  amount_due: number;
  status: 'draft' | 'sent' | 'paid' | 'overdue' | 'cancelled';
  notes?: string;
  terms?: string;
  line_items: InvoiceLineItem[];
  created_at: string;
  updated_at: string;
  sent_at?: string;
  paid_at?: string;
}

interface InvoiceLineItem {
  id: string;
  description: string;
  quantity: number;
  unit_price: number;
  amount: number;
  tax_rate: number;
  tax_amount: number;
  account_code?: string;
}

// Tax Optimization
interface TaxOptimization {
  total_deductions: number;
  potential_savings: number;
  recommendations: TaxRecommendation[];
  quarterly_estimates: QuarterlyEstimate[];
}

interface TaxRecommendation {
  category: string;
  amount: number;
  description: string;
  priority: 'high' | 'medium' | 'low';
}

interface QuarterlyEstimate {
  quarter: string;
  due_date: string;
  amount: number;
}

// Compliance
interface ComplianceCheck {
  overall_score: number;
  overall_status: 'compliant' | 'warning' | 'critical';
  indicators: ComplianceIndicator[];
  total_transactions: number;
  compliant_transactions: number;
  non_compliant_transactions: number;
  recommendations: ComplianceRecommendation[];
}

interface ComplianceIndicator {
  id: string;
  name: string;
  status: 'compliant' | 'warning' | 'critical';
  score: number;
  description: string;
  last_checked: string;
}

interface ComplianceRecommendation {
  priority: 'high' | 'medium' | 'low';
  category: string;
  title: string;
  description: string;
  action: string;
}
```

---

## Common Issues & Solutions

### Issue: CORS Error

**Error:** `Access to fetch at 'http://localhost:8000/api/...' from origin 'http://localhost:3000' has been blocked by CORS policy`

**Solution:** Backend is already configured for this. Make sure you're using `http://localhost:3000` (not `http://127.0.0.1:3000`).

### Issue: 401 Unauthorized

**Error:** `{"detail": "Unauthorized"}`

**Solution:** Include Clerk auth token in request headers:
```typescript
headers: {
  'Authorization': `Bearer ${await getToken()}`
}
```

### Issue: 422 Validation Error

**Error:** `{"detail": [{"loc": ["body", "field"], "msg": "field required"}]}`

**Solution:** Check that your request body matches the expected Pydantic model. See API docs at `/docs` for exact schema.

---

## Next Steps

1. ✅ Backend is running at `http://localhost:8000`
2. ✅ All endpoints are properly registered
3. ✅ CORS is configured for your frontend
4. ✅ Type definitions match your TypeScript interfaces

**You're ready to integrate!** 🎉

Start your frontend with:
```bash
npm run dev
```

And test the API calls from your Next.js components.

---

## Support

If you encounter any issues:

1. Check the interactive API docs: **http://localhost:8000/docs**
2. Review the comprehensive documentation:
   - [INVOICING_AND_REPORTS.md](./INVOICING_AND_REPORTS.md)
   - [FRONTEND_INTEGRATION_FIXES.md](./FRONTEND_INTEGRATION_FIXES.md)
3. Check backend logs for error details

Happy integrating! 🚀
