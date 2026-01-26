# ReconAI Backend Security Remediation (P0 + P1)

## Summary
This document describes the security fixes applied to the ReconAI backend codebase.

## Files Modified (12 files, +99/-92 lines)

### 1. SQL Injection Prevention (CRITICAL)
Column allowlists added to prevent SQL injection via dynamic UPDATE statements.

| File | Function | Fix Applied |
|------|----------|-------------|
| `app/bills/engine.py` | `update_vendor()` | Added allowlist: `name, email, phone, address, payment_terms, ein, requires_1099, notes, is_active` |
| `app/invoicing/engine.py` | `update_customer()` | Added allowlist: `name, email, phone, billing_address, shipping_address, payment_terms, tax_rate, notes, is_active` |
| `app/routers/customers.py` | `update_customer()` | Added allowlist: `name, email, phone, company_name, address_line1, address_line2, city, state, zip, country, tax_id, payment_terms, notes, is_active` |
| `app/routers/entities.py` | `update_entity()` | Added allowlist: `name, legal_name, ein, entity_type, industry, address_line1, city, state, zip, country, default_currency` |
| `app/routers/invoices.py` | `update_invoice()` | Added allowlist: `invoice_date, due_date, notes, terms, discount_amount, shipping_amount, status` |
| `app/routers/stripe_webhooks.py` | `update_organization_subscription()` | Added allowlist: `tier, subscription_status, stripe_customer_id, stripe_subscription_id, subscription_end_date` |
| `app/routers/govcon_audit_verify_api.py` | `govcon_audit_verify()` | Table name allowlist validation: `audit_events, audit_log, mvp_audit_events` |
| `app/routers/govcon_evidence_api.py` | `govcon_evidence()` | Table name allowlist validation: `audit_events, audit_log, mvp_audit_events` |

### 2. Runtime Break Fix
| File | Issue | Fix |
|------|-------|-----|
| `app/invoicing/models.py` | Undefined `Dict` type | Added `Dict` to typing imports |

### 3. Bare `except:` Statements Fixed
| File | Lines | Fix |
|------|-------|-----|
| `app/invoicing/engine.py` | Line 323 | Changed to `except (ValueError, IndexError):` |
| `app/reconai_core/bank_parsers.py` | Lines 47, 115, 176, 247, 311, 369, 429 | Changed all 7 occurrences to `except (ValueError, IndexError):` |

### 4. Function Deduplication
| File | Issue | Fix |
|------|-------|-----|
| `app/stores.py` | Duplicate `set_merchant_feedback`, `get_merchant_feedback`, `get_all_merchant_feedback` functions | Consolidated to single authoritative implementation using `app.db.DB_PATH` |

### 5. CORS Lockdown (SECURITY)
| File | Issue | Fix |
|------|-------|-----|
| `app/main.py` | Permissive regex `r"^https://.*\.vercel\.app$"` | Restricted to `r"^https://reconai-frontend(-[a-z0-9]+)?\.vercel\.app$"` |

## Installation Steps

### Step 1: Backup Current Code
```bash
cd /path/to/reconai-backend
git stash  # or create a backup branch
```

### Step 2: Apply Changes
Copy all modified files from this package to your codebase, maintaining the same directory structure:
```
app/
├── bills/engine.py
├── invoicing/engine.py
├── invoicing/models.py
├── main.py
├── reconai_core/bank_parsers.py
├── routers/
│   ├── customers.py
│   ├── entities.py
│   ├── govcon_audit_verify_api.py
│   ├── govcon_evidence_api.py
│   ├── invoices.py
│   └── stripe_webhooks.py
└── stores.py
```

### Step 3: Verify Syntax
```bash
python -m py_compile app/stores.py app/main.py app/invoicing/models.py \
    app/invoicing/engine.py app/bills/engine.py app/reconai_core/bank_parsers.py \
    app/routers/customers.py app/routers/entities.py app/routers/invoices.py \
    app/routers/stripe_webhooks.py app/routers/govcon_audit_verify_api.py \
    app/routers/govcon_evidence_api.py
```

### Step 4: Run Tests (if available)
```bash
pytest
```

### Step 5: Deploy
```bash
git add .
git commit -m "security: P0+P1 remediation - SQL injection prevention, CORS lockdown, exception handling"
git push origin main
```

## Verification Checklist

- [ ] All Python files pass syntax check
- [ ] Application starts without errors
- [ ] API endpoints respond correctly
- [ ] CORS allows reconai-frontend.vercel.app
- [ ] CORS blocks other *.vercel.app domains
- [ ] Update operations work with allowed fields
- [ ] Update operations reject disallowed fields (ignored, not errors)

## Security Notes

1. **SQL Injection Prevention**: All dynamic UPDATE statements now use explicit column allowlists. Fields not in the allowlist are silently ignored (not errored) to maintain backward compatibility.

2. **CORS Lockdown**: The new regex pattern `^https://reconai-frontend(-[a-z0-9]+)?\.vercel\.app$` only allows:
   - `reconai-frontend.vercel.app` (production)
   - `reconai-frontend-abc123.vercel.app` (preview deployments)

   Other Vercel domains are blocked.

3. **Exception Handling**: Date parsing exceptions now catch specific types (`ValueError`, `IndexError`) instead of bare `except:`.

## Rollback Instructions

If issues occur, revert to the previous code:
```bash
git revert HEAD
# or
git stash pop
```

---
Generated: 2026-01-26
Remediation Type: P0 + P1 Security Fixes
