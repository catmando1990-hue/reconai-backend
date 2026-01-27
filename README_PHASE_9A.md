# Phase 9A — Audit Export v2 Backend

Evidence-Grade Financial Export Bundle for compliance and audit purposes.

## Overview

Phase 9A implements a new `POST /api/audit-exports/v2` endpoint that generates comprehensive audit packages containing statements, asset snapshots, and liabilities data as a streamed ZIP file.

### Key Features

- **Manual Execution Only** — No automation, no background workers
- **No Plaid Calls** — Uses stored/derived data only
- **Streaming Response** — ZIP assembled in-memory, no temp files
- **Evidence-Grade Hashing** — SHA-256 for all files + manifest
- **RBAC Fail-Closed** — Admin/org:admin roles required
- **Org Isolation** — All queries scoped to authenticated organization
- **Full Audit Logging** — All operations logged

---

## Endpoint Usage

### Generate Audit Export v2

```http
POST /api/audit-exports/v2
Authorization: Bearer <token>
X-Request-ID: <uuid>
Content-Type: application/json

{
  "include_statements": true,
  "include_assets": true,
  "include_liabilities": true
}
```

**Response:** Streamed ZIP file

**Headers:**
- `X-Request-ID`: Request trace identifier
- `X-Export-Manifest-Hash`: SHA-256 of manifest.json
- `X-Export-Type`: audit_export_v2
- `Content-Disposition`: attachment; filename="audit-export-{org_id}-{timestamp}.zip"

### Preview Export Contents

```http
GET /api/audit-exports/v2/preview
Authorization: Bearer <token>
X-Request-ID: <uuid>
```

**Response:** JSON summary of available data without generating the ZIP.

---

## Required Roles

| Role | Access |
|------|--------|
| `admin` | Full access |
| `org:admin` | Full access |
| `owner` | Full access |
| Other | 403 Forbidden |

**RBAC is fail-closed:** If permission check fails, the request is denied.

---

## ZIP Logical Structure

```
audit-export-{org_id}-{utc_timestamp}.zip
├─ statements/
│  └─ statements.json
├─ assets/
│  └─ asset_snapshot.json
├─ liabilities/
│  └─ liabilities.json
├─ manifest.json
└─ hashes.json
```

### File Descriptions

| File | Description |
|------|-------------|
| `statements/statements.json` | Stored statement and receipt records from local database |
| `assets/asset_snapshot.json` | Derived asset data from transaction history |
| `liabilities/liabilities.json` | Derived liability data from transaction history |
| `manifest.json` | Export metadata (version, org_id, counts, timestamps) |
| `hashes.json` | SHA-256 hashes for all files including manifest |

---

## Hashing Rules

### Algorithm
- **SHA-256** (lowercase hex string)

### Coverage
- Every file in the ZIP has its hash recorded in `hashes.json`
- `manifest.json` hash is included
- `hashes.json` includes a `contents_order_hash` for deterministic verification

### Example hashes.json

```json
{
  "generated_at": "2026-01-26T20:00:00.000000+00:00",
  "algorithm": "SHA-256",
  "file_hashes": {
    "statements/statements.json": "a1b2c3...",
    "assets/asset_snapshot.json": "d4e5f6...",
    "liabilities/liabilities.json": "g7h8i9...",
    "manifest.json": "j0k1l2..."
  },
  "contents_order": [
    "assets/asset_snapshot.json",
    "liabilities/liabilities.json",
    "manifest.json",
    "statements/statements.json"
  ],
  "contents_order_hash": "m3n4o5..."
}
```

---

## manifest.json Format

```json
{
  "manifest_version": "v2",
  "org_id": "org_123",
  "generated_at": "2026-01-26T20:00:00.000000+00:00",
  "generated_by": "user_456",
  "request_id": "req_abc123",
  "included_sections": ["statements", "assets", "liabilities"],
  "counts": {
    "statements": 5,
    "receipts": 10,
    "assets_accounts": 3,
    "liabilities_accounts": 2
  },
  "files": [
    "statements/statements.json",
    "assets/asset_snapshot.json",
    "liabilities/liabilities.json"
  ],
  "export_type": "audit_export_v2",
  "data_sources": {
    "statements": "local_database",
    "assets": "derived_from_transactions",
    "liabilities": "derived_from_transactions"
  },
  "compliance_notes": [
    "This export uses locally stored data only.",
    "No live Plaid API calls were made during export generation.",
    "For authoritative financial data, use the respective Plaid product endpoints."
  ]
}
```

---

## Audit Events

| Event Type | Description |
|------------|-------------|
| `audit_export_v2_generated` | Export generation started |
| `audit_export_v2_downloaded` | Export streamed to client |
| `audit_export_v2_access_denied` | Permission denied (403) |
| `audit_export_v2_preview` | Preview endpoint accessed |

All events are logged to the append-only `audit_events` table with hash chaining.

---

## Files Created

| File | Description |
|------|-------------|
| `app/routers/audit_exports_v2.py` | FastAPI router for /api/audit-exports/v2 |
| `app/services/audit_export_builder_v2.py` | Pure builder service (no I/O, no Plaid) |
| `app/schemas/audit_export_v2.py` | Pydantic models (ManifestV2, HashesV2, etc.) |
| `app/schemas/__init__.py` | Schemas package init |

## Files Modified

| File | Change |
|------|--------|
| `app/main.py` | Import and register audit_exports_v2 router |
| `app/services/audit_service.py` | Add AUDIT_EVENT_EXPORT_V2_* constants |

---

## Verification Checklist

- [ ] Endpoint streams ZIP bytes (no temp files)
- [ ] All data sourced from existing Phase 7.1/8 stores
- [ ] manifest.json includes version "v2"
- [ ] hashes.json includes SHA-256 for every file + manifest
- [ ] RBAC fail-closed (non-admin gets 403)
- [ ] Org isolation on all queries
- [ ] Structured errors include request_id
- [ ] Audit events logged for all operations
- [ ] No automation introduced (no cron, no background workers)
- [ ] No new Plaid API calls

### Manual Testing

1. **Test RBAC Denial:**
   ```bash
   curl -X POST http://localhost:8000/api/audit-exports/v2 \
     -H "Authorization: Bearer <viewer_token>" \
     -H "X-Request-ID: test-123"
   # Expected: 403 Forbidden
   ```

2. **Test Export Generation:**
   ```bash
   curl -X POST http://localhost:8000/api/audit-exports/v2 \
     -H "Authorization: Bearer <admin_token>" \
     -H "X-Request-ID: test-456" \
     -o audit-export.zip
   # Expected: ZIP file downloaded
   ```

3. **Verify ZIP Contents:**
   ```bash
   unzip -l audit-export.zip
   # Expected: statements/, assets/, liabilities/, manifest.json, hashes.json
   ```

4. **Verify Hashes:**
   ```bash
   unzip audit-export.zip
   sha256sum statements/statements.json
   # Compare with value in hashes.json
   ```

---

## Rollback Steps

If issues are discovered:

1. **Remove router registration from main.py:**
   ```python
   # Comment out or remove these lines:
   # from app.routers.audit_exports_v2 import router as audit_exports_v2_router
   # app.include_router(audit_exports_v2_router)
   ```

2. **Optionally remove files** (safe, no dependencies):
   - `app/routers/audit_exports_v2.py`
   - `app/services/audit_export_builder_v2.py`
   - `app/schemas/audit_export_v2.py`

3. **Remove audit constants from audit_service.py** (optional, harmless if left)

4. **Restart application**

---

## Data Sources

| Section | Source | Notes |
|---------|--------|-------|
| Statements | `statements` table | Local database only |
| Receipts | `receipts` table | Local database only |
| Assets | `core_transactions` table | Derived from transaction history |
| Liabilities | `core_transactions` table | Derived (accounts with negative balance) |

**Important:** This endpoint does NOT make any Plaid API calls. For authoritative Plaid data, use the Phase 8 endpoints directly.

---

## Canonical Laws Compliance

| Law | Status |
|-----|--------|
| Manual execution only | ✅ POST endpoint only, no automation |
| No background workers | ✅ In-memory assembly, streaming response |
| No new Plaid calls | ✅ Uses stored/derived data only |
| RBAC fail-closed | ✅ 403 on permission failure |
| Org isolation | ✅ All queries include organization_id |
| Audit logging | ✅ All operations logged |
| Structured errors | ✅ request_id in all responses |
