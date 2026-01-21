# PLAID CONTRACT FREEZE — DO NOT MODIFY

**Frozen As Of:** 2024-01-20
**Phase:** 4/4 System Hardening
**Status:** PRODUCTION LOCKED

---

## CONTRACT SURFACE (READ-ONLY REFERENCE)

### Routes (app/routers/plaid_v2.py)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/plaid/create-link-token` | Create Plaid Link token for user |
| POST | `/api/plaid/exchange-public-token` | Exchange public token for access token |
| POST | `/api/plaid/sync-transactions` | Cursor-based transaction sync |
| GET | `/api/plaid/items` | List org's connected Plaid items |
| POST | `/api/plaid/webhook` | Receive Plaid webhooks |
| DELETE | `/api/plaid/items/{item_id}` | Disconnect Plaid item |

### Tables (app/db.py)

| Table | Purpose | Mutable? |
|-------|---------|----------|
| `plaid_items` | Org-scoped Plaid connections | Yes (status updates) |
| `plaid_audit_log` | Immutable audit trail | APPEND ONLY |
| `plaid_webhook_events` | Webhook idempotency | Yes (processed flag) |

### Security Guarantees

1. **Auth Protection**: All routes require `get_current_context`
2. **Org-Scoped**: All data filtered by `organization_id`
3. **Token Encryption**: Access tokens encrypted with AES-256-GCM
4. **Webhook Verification**: HMAC-SHA256 signature verification
5. **Audit Logging**: All operations logged immutably

### Environment Variables (REQUIRED)

```
PLAID_CLIENT_ID        # Plaid client ID
PLAID_SECRET           # Plaid secret key
PLAID_ENV              # sandbox | development | production
PLAID_WEBHOOK_SECRET   # Webhook signature verification key
ENCRYPTION_KEY         # AES-256 key for token encryption
```

---

## FREEZE RULES

1. **NO NEW ENDPOINTS** — Do not add routes to plaid_v2.py
2. **NO SCHEMA CHANGES** — Do not modify plaid_* table structures
3. **NO NEW PRODUCTS** — Products locked to: transactions, auth
4. **NO TOKEN CHANGES** — Do not modify encryption/decryption logic
5. **NO WEBHOOK CHANGES** — Do not add new webhook handlers

---

## MODIFICATION PROCEDURE

If changes are REQUIRED:

1. Create RFC document with business justification
2. Security review mandatory
3. Backwards compatibility required
4. Migration plan for existing data
5. Audit trail must be preserved
6. Update this FROZEN.md with change log

---

## CHANGE LOG

| Date | Change | Author | Approved By |
|------|--------|--------|-------------|
| 2024-01-20 | Initial freeze | Claude Code | — |

---

**WARNING**: Any modification to Plaid modules without following the above
procedure is a policy violation. This freeze exists to protect production
stability and user financial data.
