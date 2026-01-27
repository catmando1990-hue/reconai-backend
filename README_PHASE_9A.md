# Phase 9A + 10A — Audit Export v2 Backend

Evidence-Grade Financial Export Bundle for compliance and audit purposes.

## Overview

Phase 9A implements a new `POST /api/audit-exports/v2` endpoint that generates comprehensive audit packages containing statements, asset snapshots, and liabilities data as a streamed ZIP file.

**Phase 10A** extends the manifest with a static, versioned GovCon/DCAA mapping that classifies exported evidence without interpretation.

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
  ],
  "govcon_mapping": {
    "standard": "DCAA",
    "version": "2024.1",
    "sections": {
      "statements": {
        "dcaa_refs": [
          "SF 1408 – Accounting System Adequacy",
          "FAR 31.201-2"
        ],
        "description": "Source financial statements used as primary accounting evidence."
      },
      "assets": {
        "dcaa_refs": [
          "SF 1408 – Financial Capability",
          "FAR 9.104-1"
        ],
        "description": "Point-in-time asset snapshots demonstrating financial responsibility."
      },
      "liabilities": {
        "dcaa_refs": [
          "SF 1408 – Financial Capability",
          "FAR 31.201-3"
        ],
        "description": "Reported obligations relevant to financial condition and risk."
      }
    }
  }
}
```

---

## Phase 10A: GovCon/DCAA Mapping

### Overview

The `govcon_mapping` field in `manifest.json` provides a static, versioned classification of exported evidence according to DCAA and FAR references.

### Key Properties

- **Static Mapping** — Hardcoded constant, no dynamic logic
- **Versioned** — Explicit version string (e.g., "2024.1")
- **Conditional Inclusion** — Only includes mappings for sections present in the export
- **No Inference** — Purely descriptive references, no compliance claims

### Mapping Structure

| Field | Type | Description |
|-------|------|-------------|
| `standard` | string | Always "DCAA" |
| `version` | string | Mapping version (e.g., "2024.1") |
| `sections` | object | Per-section DCAA references |

### Section Mappings

| Section | DCAA References | Description |
|---------|-----------------|-------------|
| `statements` | SF 1408 – Accounting System Adequacy, FAR 31.201-2 | Source financial statements used as primary accounting evidence |
| `assets` | SF 1408 – Financial Capability, FAR 9.104-1 | Point-in-time asset snapshots demonstrating financial responsibility |
| `liabilities` | SF 1408 – Financial Capability, FAR 31.201-3 | Reported obligations relevant to financial condition and risk |

### Conditional Logic

The `govcon_mapping` field is **only included** if at least one section is present in the export. Each section mapping is only included if that section was requested and included.

**Example: Export with only statements:**
```json
{
  "govcon_mapping": {
    "standard": "DCAA",
    "version": "2024.1",
    "sections": {
      "statements": {
        "dcaa_refs": ["SF 1408 – Accounting System Adequacy", "FAR 31.201-2"],
        "description": "Source financial statements used as primary accounting evidence."
      }
    }
  }
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
| `audit_export_v2_govcon_mapped` | GovCon/DCAA mapping injected into manifest (Phase 10A) |

All events are logged to the append-only `audit_events` table with hash chaining.

### GovCon Mapping Event Payload

The `audit_export_v2_govcon_mapped` event includes:
```json
{
  "org_id": "org_123",
  "mapping_standard": "DCAA",
  "mapping_version": "2024.1",
  "mapped_sections": ["statements", "assets", "liabilities"]
}
```

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

### Phase 9A
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

### Phase 10A
- [ ] `govcon_mapping` field present in manifest.json
- [ ] Mapping is static (no dynamic logic)
- [ ] Version is explicit ("2024.1")
- [ ] Only included sections have mappings
- [ ] No compliance scoring or claims
- [ ] `audit_export_v2_govcon_mapped` event logged when mapping applied
- [ ] No frontend changes
- [ ] No new endpoints added

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

### Phase 10A Additional Compliance

| Requirement | Status |
|-------------|--------|
| Static mapping only | ✅ Hardcoded constant, no dynamic logic |
| No compliance scoring | ✅ Descriptive references only |
| No inference | ✅ No automated recommendations |
| Conditional inclusion | ✅ Only maps present sections |
| Versioned explicitly | ✅ "2024.1" version string |
| No frontend changes | ✅ Backend only |
| No new endpoints | ✅ Extends existing manifest only |

---

## Phase 11A: Export Signing + Tamper-Evidence

### Overview

Phase 11A adds cryptographic signing (Ed25519) and a deterministic hash chain to the Audit Export v2 ZIP, enabling independent verification of integrity and provenance without requiring the server.

### Signing Model

1. **Hash Chain** — A deterministic chain is computed over all section file hashes (sorted by filename):
   ```
   H0 = SHA256(file_1_hash)
   H1 = SHA256(H0 || file_2_hash)
   ...
   Hn = chain_root
   ```
2. **Ed25519 Signature** — The `chain_root` is signed using an Ed25519 private key loaded from the `AUDIT_EXPORT_SIGNING_PRIVATE_KEY` environment variable (hex-encoded 32-byte seed).
3. **Self-Verification** — The signature is verified immediately after signing at generation time. If self-verification fails, signing artifacts are excluded entirely.

### Graceful Degradation

If `AUDIT_EXPORT_SIGNING_PRIVATE_KEY` is not set:
- No `integrity` block in manifest
- No `signatures/` folder in ZIP
- No signing audit events
- Export works identically to Phase 9A/10A

**No runtime key generation** — this is a hard constraint.

### ZIP Structure (with signing)

```
audit-export-{org_id}-{utc_timestamp}.zip
├─ statements/
│  └─ statements.json
├─ assets/
│  └─ asset_snapshot.json
├─ liabilities/
│  └─ liabilities.json
├─ signatures/
│  ├─ signature.ed25519       (raw 64-byte Ed25519 signature)
│  ├─ public_key.ed25519      (raw 32-byte Ed25519 public key)
│  └─ signature.json          (algorithm, chain_root, signed_at, key_id, manifest_version)
├─ manifest.json
└─ hashes.json
```

### Manifest `integrity` Block

When signing is applied, `manifest.json` includes:

```json
{
  "integrity": {
    "hash_chain": {
      "algorithm": "sha256",
      "root": "<chain_root hex>"
    },
    "signature": {
      "algorithm": "ed25519",
      "key_id": "<first 16 chars of SHA256(public_key)>",
      "signed_at": "<UTC ISO8601>"
    }
  }
}
```

The `integrity` field is strongly typed via `IntegrityBlock` Pydantic model (not a loose dict).

### `signatures/signature.json` Format

```json
{
  "algorithm": "ed25519",
  "chain_root": "<chain_root hex>",
  "signed_at": "<UTC ISO8601>",
  "key_id": "<key_id>",
  "manifest_version": "v2"
}
```

### Offline Verification Steps

To independently verify an export:

1. Extract the ZIP
2. Compute SHA-256 of each section file
3. Sort hashes by filename and recompute the hash chain
4. Compare the computed `chain_root` to `manifest.json > integrity > hash_chain > root`
5. Load `signatures/public_key.ed25519` (32 bytes)
6. Verify `signatures/signature.ed25519` against the `chain_root` using Ed25519

### What the Signature Proves vs. Does NOT Prove

| Proves | Does NOT Prove |
|--------|----------------|
| Files have not been tampered with since generation | Compliance with any standard |
| Export was produced by the holder of the signing key | Accuracy of underlying data |
| Deterministic ordering was maintained | Completeness of financial records |

### Phase 11A Audit Events

| Event Type | Description |
|------------|-------------|
| `audit_export_v2_signed` | Export signed with Ed25519 (includes key_id, chain_root prefix) |
| `audit_export_v2_signature_verified` | Self-verification passed at generation time |

### Phase 11A Verification Checklist

- [ ] File hashes sorted deterministically before chain computation
- [ ] Hash chain uses `SHA256(prev \|\| next)` iteratively
- [ ] Ed25519 key loaded from `AUDIT_EXPORT_SIGNING_PRIVATE_KEY` env var
- [ ] Public key embedded in ZIP (`signatures/public_key.ed25519`)
- [ ] `integrity` block present in `manifest.json` when signing applied
- [ ] `signatures/signature.json` includes algorithm, chain_root, signed_at, key_id, manifest_version
- [ ] Audit events emitted for signing and self-verification
- [ ] Streaming response preserved (no new disk I/O)
- [ ] No runtime key generation
- [ ] No frontend changes
- [ ] No new endpoints added
- [ ] No compliance claims in signing artifacts

### Phase 11A Canonical Laws Compliance

| Requirement | Status |
|-------------|--------|
| No runtime key generation | ✅ Key from env var only |
| No background verification | ✅ Self-verify at generation time only |
| No new endpoints | ✅ Extends existing build pipeline |
| No frontend changes | ✅ Backend only |
| No compliance claims | ✅ Signing proves integrity/provenance only |
| Graceful degradation | ✅ No key = no signing, export still works |
| Strong typing | ✅ `IntegrityBlock` Pydantic model on `ManifestV2` |
