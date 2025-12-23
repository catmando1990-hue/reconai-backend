# ReconAI Bookkeeper Engine

A complete double-entry bookkeeping system built into ReconAI Backend.

## Features

✅ **Chart of Accounts Management** - CRUD operations for accounts
✅ **Double-Entry Bookkeeping** - Enforced debit/credit balance
✅ **Journal Entry Processing** - Create, post, and void entries
✅ **Account Balance Calculations** - Real-time balance updates
✅ **Debit/Credit Validation** - Automatic validation rules
✅ **Trial Balance Reports** - Verify books are balanced
✅ **General Ledger** - Transaction history by account
✅ **Standard Chart of Accounts Template** - Quick setup

---

## API Endpoints

Base URL: `/api/bookkeeping`

### Chart of Accounts

#### Create Account
```http
POST /api/bookkeeping/accounts
Content-Type: application/json

{
  "account_id": "1000",
  "account_number": "1000",
  "account_name": "Cash - Operating",
  "account_type": "Asset",
  "account_subtype": "Cash",
  "description": "Primary operating cash account"
}
```

**Response:**
```json
{
  "account_id": "1000",
  "account_number": "1000",
  "account_name": "Cash - Operating",
  "account_type": "Asset",
  "account_subtype": "Cash",
  "description": "Primary operating cash account",
  "normal_balance": "Debit",
  "is_active": true,
  "current_balance": "0.00",
  "created_at": "2024-01-15T10:30:00",
  "updated_at": "2024-01-15T10:30:00"
}
```

#### List Accounts
```http
GET /api/bookkeeping/accounts?account_type=Asset&active_only=true
```

#### Get Account
```http
GET /api/bookkeeping/accounts/{account_id}
```

#### Update Account
```http
PATCH /api/bookkeeping/accounts/{account_id}
Content-Type: application/json

{
  "account_name": "Cash - Primary Operating",
  "description": "Updated description"
}
```

#### Delete Account
```http
DELETE /api/bookkeeping/accounts/{account_id}?force=false
```

#### Bulk Import Accounts
```http
POST /api/bookkeeping/accounts/bulk-import
Content-Type: application/json

{
  "accounts": [
    { "account_id": "1000", "account_number": "1000", ... },
    { "account_id": "4000", "account_number": "4000", ... }
  ]
}
```

---

### Journal Entries

#### Create Journal Entry
```http
POST /api/bookkeeping/journal-entries
Content-Type: application/json

{
  "entry_date": "2024-01-15",
  "description": "Payment received from Customer ABC",
  "reference": "INV-2024-001",
  "lines": [
    {
      "account_id": "1000",
      "debit": "1000.00",
      "credit": "0.00",
      "memo": "Cash received"
    },
    {
      "account_id": "4000",
      "debit": "0.00",
      "credit": "1000.00",
      "memo": "Revenue recognized"
    }
  ],
  "auto_post": true
}
```

**Response:**
```json
{
  "entry_id": "JE-A1B2C3D4E5F6",
  "entry_number": "JE-2024-0001",
  "entry_date": "2024-01-15",
  "description": "Payment received from Customer ABC",
  "reference": "INV-2024-001",
  "lines": [
    {
      "line_id": "JE-A1B2C3D4E5F6-L1",
      "account_id": "1000",
      "account_name": "Cash - Operating",
      "debit": "1000.00",
      "credit": "0.00",
      "memo": "Cash received"
    },
    {
      "line_id": "JE-A1B2C3D4E5F6-L2",
      "account_id": "4000",
      "account_name": "Service Revenue",
      "debit": "0.00",
      "credit": "1000.00",
      "memo": "Revenue recognized"
    }
  ],
  "status": "posted",
  "created_at": "2024-01-15T10:30:00",
  "posted_at": "2024-01-15T10:30:01"
}
```

#### List Journal Entries
```http
GET /api/bookkeeping/journal-entries?start_date=2024-01-01&end_date=2024-01-31&status=posted
```

#### Get Journal Entry
```http
GET /api/bookkeeping/journal-entries/{entry_id}
```

#### Post Journal Entry
```http
POST /api/bookkeeping/journal-entries/{entry_id}/post
```

#### Void Journal Entry
```http
POST /api/bookkeeping/journal-entries/{entry_id}/void?create_reversing_entry=true
```

---

### Reports

#### Trial Balance
```http
GET /api/bookkeeping/trial-balance?as_of_date=2024-01-31
```

**Response:**
```json
{
  "as_of_date": "2024-01-31",
  "accounts": [
    {
      "account_id": "1000",
      "account_number": "1000",
      "account_name": "Cash - Operating",
      "account_type": "Asset",
      "debit_balance": "25000.00",
      "credit_balance": "0.00",
      "net_balance": "25000.00",
      "normal_balance": "Debit"
    },
    {
      "account_id": "4000",
      "account_number": "4000",
      "account_name": "Service Revenue",
      "account_type": "Revenue",
      "debit_balance": "0.00",
      "credit_balance": "25000.00",
      "net_balance": "25000.00",
      "normal_balance": "Credit"
    }
  ],
  "total_debits": "25000.00",
  "total_credits": "25000.00",
  "is_balanced": true,
  "difference": "0.00"
}
```

#### General Ledger
```http
GET /api/bookkeeping/general-ledger/1000?start_date=2024-01-01&end_date=2024-01-31
```

**Response:**
```json
{
  "account": {
    "account_id": "1000",
    "account_name": "Cash - Operating",
    "account_type": "Asset",
    ...
  },
  "entries": [
    {
      "entry_id": "JE-A1B2C3D4E5F6",
      "entry_number": "JE-2024-0001",
      "entry_date": "2024-01-15",
      "description": "Payment received from customer",
      "reference": "INV-001",
      "debit": "1000.00",
      "credit": "0.00",
      "balance": "1000.00"
    },
    {
      "entry_id": "JE-B2C3D4E5F6G7",
      "entry_number": "JE-2024-0002",
      "entry_date": "2024-01-20",
      "description": "Office rent payment",
      "reference": "CHK-1234",
      "debit": "0.00",
      "credit": "500.00",
      "balance": "500.00"
    }
  ],
  "opening_balance": "0.00",
  "closing_balance": "500.00",
  "period_start": "2024-01-01",
  "period_end": "2024-01-31"
}
```

#### Account Balance
```http
GET /api/bookkeeping/account-balance/1000
```

**Response:**
```json
{
  "account_id": "1000",
  "account_name": "Cash - Operating",
  "account_type": "Asset",
  "normal_balance": "Debit",
  "current_balance": "25000.00"
}
```

---

### Utility Endpoints

#### Validate Entry
```http
GET /api/bookkeeping/validate-entry?total_debits=1000.00&total_credits=1000.00
```

**Response:**
```json
{
  "is_balanced": true,
  "total_debits": "1000.00",
  "total_credits": "1000.00",
  "difference": "0.00",
  "valid": true
}
```

#### Get Chart of Accounts Template
```http
GET /api/bookkeeping/chart-of-accounts/template
```

Returns a standard chart of accounts with 50+ pre-configured accounts.

#### Health Check
```http
GET /api/bookkeeping/health
```

---

## Double-Entry Bookkeeping Rules

### 1. Debits Must Equal Credits
Every journal entry must have equal total debits and credits.

```json
{
  "entry_date": "2024-01-15",
  "description": "Example entry",
  "lines": [
    { "account_id": "1000", "debit": "500.00", "credit": "0.00" },
    { "account_id": "5000", "debit": "500.00", "credit": "0.00" },
    { "account_id": "2000", "debit": "0.00", "credit": "1000.00" }
  ]
}
```
✅ Total Debits: $1,000 = Total Credits: $1,000

### 2. Each Line: Debit XOR Credit
Every line must have **either** a debit **or** a credit, not both, not neither.

❌ **Invalid:** `{ "debit": "500.00", "credit": "500.00" }`
❌ **Invalid:** `{ "debit": "0.00", "credit": "0.00" }`
✅ **Valid:** `{ "debit": "500.00", "credit": "0.00" }`
✅ **Valid:** `{ "debit": "0.00", "credit": "500.00" }`

### 3. Normal Balance Rules

| Account Type | Normal Balance | Increases With | Decreases With |
|--------------|----------------|----------------|----------------|
| Asset        | Debit          | Debit          | Credit         |
| Expense      | Debit          | Debit          | Credit         |
| Liability    | Credit         | Credit         | Debit          |
| Equity       | Credit         | Credit         | Debit          |
| Revenue      | Credit         | Credit         | Debit          |

### 4. Minimum Two Lines
Every journal entry must have at least 2 lines (one debit, one credit).

---

## Common Transaction Examples

### 1. Customer Payment Received
```json
{
  "entry_date": "2024-01-15",
  "description": "Payment received from Customer ABC",
  "reference": "INV-001",
  "lines": [
    { "account_id": "1000", "debit": "1000.00", "credit": "0.00", "memo": "Cash received" },
    { "account_id": "4000", "debit": "0.00", "credit": "1000.00", "memo": "Revenue recognized" }
  ]
}
```
**Effect:** Cash increases (debit), Revenue increases (credit)

### 2. Pay Rent Expense
```json
{
  "entry_date": "2024-01-01",
  "description": "January office rent",
  "reference": "CHK-1234",
  "lines": [
    { "account_id": "5060", "debit": "1500.00", "credit": "0.00", "memo": "Rent expense" },
    { "account_id": "1000", "debit": "0.00", "credit": "1500.00", "memo": "Cash payment" }
  ]
}
```
**Effect:** Rent Expense increases (debit), Cash decreases (credit)

### 3. Purchase Equipment on Credit
```json
{
  "entry_date": "2024-01-10",
  "description": "Purchase laptop for business use",
  "reference": "INV-LAPTOP-001",
  "lines": [
    { "account_id": "1500", "debit": "2000.00", "credit": "0.00", "memo": "Laptop equipment" },
    { "account_id": "2000", "debit": "0.00", "credit": "2000.00", "memo": "Accounts payable" }
  ]
}
```
**Effect:** Equipment increases (debit), Accounts Payable increases (credit)

### 4. Pay Down Credit Card
```json
{
  "entry_date": "2024-01-20",
  "description": "Credit card payment",
  "reference": "PAYMENT-CC",
  "lines": [
    { "account_id": "2100", "debit": "500.00", "credit": "0.00", "memo": "Reduce CC balance" },
    { "account_id": "1000", "debit": "0.00", "credit": "500.00", "memo": "Cash payment" }
  ]
}
```
**Effect:** Credit Card Liability decreases (debit), Cash decreases (credit)

### 5. Owner Investment
```json
{
  "entry_date": "2024-01-01",
  "description": "Owner capital contribution",
  "reference": "CAPITAL-001",
  "lines": [
    { "account_id": "1000", "debit": "10000.00", "credit": "0.00", "memo": "Cash deposit" },
    { "account_id": "3000", "debit": "0.00", "credit": "10000.00", "memo": "Owner equity" }
  ]
}
```
**Effect:** Cash increases (debit), Owner's Equity increases (credit)

---

## Account Numbering Convention

The standard chart of accounts uses the following numbering:

| Range      | Account Type              | Examples                    |
|------------|---------------------------|-----------------------------|
| 1000-1999  | Assets                    | Cash, AR, Equipment         |
| 2000-2999  | Liabilities               | AP, Credit Cards, Loans     |
| 3000-3999  | Equity                    | Owner's Equity, Retained    |
| 4000-4999  | Revenue                   | Sales, Service Revenue      |
| 5000-5999  | Operating Expenses        | Rent, Utilities, Marketing  |
| 6000-6999  | Cost of Goods Sold        | Direct costs                |
| 7000-7999  | Other Income/Expenses     | Interest, Depreciation      |

---

## Quick Start Guide

### 1. Set Up Chart of Accounts

**Option A: Use Template**
```bash
curl http://localhost:8000/api/bookkeeping/chart-of-accounts/template
# Copy the accounts array from response

curl -X POST http://localhost:8000/api/bookkeeping/accounts/bulk-import \
  -H "Content-Type: application/json" \
  -d '{"accounts": [...]}'
```

**Option B: Create Manually**
```bash
curl -X POST http://localhost:8000/api/bookkeeping/accounts \
  -H "Content-Type: application/json" \
  -d '{
    "account_id": "1000",
    "account_number": "1000",
    "account_name": "Cash",
    "account_type": "Asset"
  }'
```

### 2. Create Your First Journal Entry
```bash
curl -X POST http://localhost:8000/api/bookkeeping/journal-entries \
  -H "Content-Type: application/json" \
  -d '{
    "entry_date": "2024-01-15",
    "description": "Initial capital investment",
    "lines": [
      { "account_id": "1000", "debit": "10000.00", "credit": "0.00" },
      { "account_id": "3000", "debit": "0.00", "credit": "10000.00" }
    ],
    "auto_post": true
  }'
```

### 3. Check Your Trial Balance
```bash
curl http://localhost:8000/api/bookkeeping/trial-balance
```

Should show:
- Total Debits: $10,000
- Total Credits: $10,000
- is_balanced: true

---

## Error Handling

### Common Validation Errors

**Unbalanced Entry**
```json
{
  "detail": "Invalid journal entry: Entry is not balanced: Debits=1000.00, Credits=900.00"
}
```

**Missing Debit/Credit**
```json
{
  "detail": "Invalid journal entry: Line 1: Must have either debit OR credit, not both or neither"
}
```

**Account Not Found**
```json
{
  "detail": "Account 9999 does not exist"
}
```

**Duplicate Account**
```json
{
  "detail": "Account with ID '1000' or number '1000' already exists"
}
```

---

## Database Schema

### `accounts` Table
- `account_id` (TEXT, PRIMARY KEY)
- `account_number` (TEXT, UNIQUE)
- `account_name` (TEXT)
- `account_type` (TEXT: Asset/Liability/Equity/Revenue/Expense)
- `account_subtype` (TEXT)
- `description` (TEXT)
- `normal_balance` (TEXT: Debit/Credit)
- `is_active` (INTEGER: 0/1)
- `parent_account_id` (TEXT, FOREIGN KEY)
- `current_balance` (TEXT: Decimal stored as string)
- `created_at` (TEXT: ISO datetime)
- `updated_at` (TEXT: ISO datetime)

### `journal_entries` Table
- `entry_id` (TEXT, PRIMARY KEY)
- `entry_number` (TEXT, UNIQUE)
- `entry_date` (TEXT: ISO date)
- `description` (TEXT)
- `reference` (TEXT)
- `status` (TEXT: draft/posted/voided)
- `created_by` (TEXT)
- `created_at` (TEXT: ISO datetime)
- `posted_at` (TEXT: ISO datetime)
- `voided_at` (TEXT: ISO datetime)

### `journal_entry_lines` Table
- `line_id` (TEXT, PRIMARY KEY)
- `entry_id` (TEXT, FOREIGN KEY)
- `account_id` (TEXT, FOREIGN KEY)
- `debit` (TEXT: Decimal)
- `credit` (TEXT: Decimal)
- `memo` (TEXT)
- `line_order` (INTEGER)

---

## Integration with ReconAI

The bookkeeping engine integrates with ReconAI's transaction classification:

1. **Classify transactions** using `/classify-transactions`
2. **Get tax/DCAA info** from classification response
3. **Create journal entries** based on classification
4. **Map to chart of accounts** using Schedule C line mappings

### Example Workflow
```python
# 1. Classify transaction
response = requests.post('/classify-transactions', json={
    'transactions': [{
        'merchant_name': 'AWS',
        'amount': 150.00,
        'date': '2024-01-15'
    }]
})

category = response.json()[0]['category']  # "Software & Subscriptions"
expense_account = "5050"  # Office Expenses (Schedule C Line 18)

# 2. Create journal entry
requests.post('/api/bookkeeping/journal-entries', json={
    'entry_date': '2024-01-15',
    'description': 'AWS hosting charges',
    'reference': 'AWS-INV-2024-01',
    'lines': [
        {'account_id': expense_account, 'debit': '150.00', 'credit': '0.00'},
        {'account_id': '2100', 'debit': '0.00', 'credit': '150.00'}  # Credit card
    ],
    'auto_post': True
})
```

---

## Best Practices

1. **Always use auto_post=true for production** - Ensures balances update immediately
2. **Use reference numbers** - Link to invoices, checks, receipts
3. **Write clear descriptions** - Future you will thank you
4. **Run trial balance regularly** - Catch errors early
5. **Use meaningful account names** - "Rent - Office Space" not just "Rent"
6. **Keep line memos** - Document each side of the transaction
7. **Void, don't delete** - Maintain audit trail with reversing entries
8. **Reconcile monthly** - Match accounts to bank statements

---

## Support

For questions or issues:
- Check trial balance if entries aren't posting
- Verify all account_ids exist before creating entries
- Ensure debits = credits before submission
- Review validation error messages carefully

Happy bookkeeping! 📒
