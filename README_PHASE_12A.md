# Phase 12A — GovCon Packet Presets

Preset-based export endpoint that assembles pre-defined evidence bundles using existing Audit Export v2 builder + signing.

## Overview

Phase 12A adds a `POST /api/audit-exports/v2/presets` endpoint that maps a preset name (e.g., `sf1408_pre_award`) to a set of required sections, then delegates to the canonical v2 builder for ZIP assembly, hashing, and signing.

### Key Properties

- **Hardcoded Presets** — `PRESET_REGISTRY` is a static dict, not a database table. New presets = code change.
- **Reuses Existing Builder** — Delegates to `build_audit_export_v2()` with section flags + packet block.
- **Reuses Existing Download** — Preset exports use the same cache + download endpoint as regular v2 exports.
- **No Compliance Claims** — Presets select sections, nothing more.
- **No Automation** — Manual execution only.
- **No Plaid Calls** — Uses stored/derived data only.

---

## Endpoint

```http
POST /api/audit-exports/v2/presets
Authorization: Bearer <token>
X-Request-ID: <uuid>
Content-Type: application/json

{
  "preset": "sf1408_pre_award",
  "options": {
    "statement_period": { "from_date": "2025-01-01", "to_date": "2025-12-31" },
    "asset_snapshot_id": null
  }
}
```

**Response:** JSON metadata with `export_id` and `download_url` (same pattern as `POST /v2`).

**Download:** Uses existing `GET /api/audit-exports/v2/download?export_id={id}`.

---

## Available Presets

| Preset | Description | Sections |
|--------|-------------|----------|
| `sf1408_pre_award` | Pre-award evidence bundle aligned to SF 1408 | statements, assets, liabilities |

---

## Preset Options

| Option | Type | Description |
|--------|------|-------------|
| `statement_period.from_date` | `string (YYYY-MM-DD)` | Start date for statement period filter (inclusive) |
| `statement_period.to_date` | `string (YYYY-MM-DD)` | End date for statement period filter (inclusive) |
| `asset_snapshot_id` | `string` | Reserved for future use (assets are derived on-demand) |

---

## Manifest `packet` Block

When generated via a preset, `manifest.json` includes:

```json
{
  "packet": {
    "preset": "sf1408_pre_award",
    "description": "Pre-award evidence bundle aligned to SF 1408.",
    "includes": ["statements", "assets", "liabilities"]
  }
}
```

The `packet` field is strongly typed via `PacketBlock` Pydantic model on `ManifestV2`.

---

## Files Created

| File | Description |
|------|-------------|
| `app/schemas/audit_export_presets.py` | `PresetType` enum, `PresetRequest`, `PresetOptions`, `StatementPeriod` models |
| `app/services/audit_export_presets.py` | Preset resolver/assembler with `PRESET_REGISTRY`, delegates to builder |
| `app/routers/audit_export_presets_v2.py` | `POST /api/audit-exports/v2/presets` endpoint |

## Files Modified

| File | Change |
|------|--------|
| `app/schemas/audit_export_v2.py` | `PacketBlock` model + `ManifestV2.packet` field |
| `app/services/audit_service.py` | `AUDIT_EVENT_EXPORT_PRESET_REQUESTED`, `AUDIT_EVENT_EXPORT_PRESET_GENERATED` constants |
| `app/services/audit_export_builder_v2.py` | `packet` param on `build_manifest()` + `build_audit_export_v2()`, date filtering on statements/receipts |
| `app/main.py` | Register `audit_export_presets_v2` router |

---

## Audit Events

| Event Type | Description |
|------------|-------------|
| `audit_export_preset_requested` | Preset export requested (includes preset name, options) |
| `audit_export_preset_generated` | Preset export generated (includes export_id, signing status) |

---

## Verification Checklist

- [ ] `POST /v2/presets` with `"preset": "sf1408_pre_award"` returns JSON with export_id + download_url
- [ ] `GET /v2/download?export_id=...` streams ZIP with all sections + signing artifacts
- [ ] manifest.json includes `packet` block with preset, description, includes
- [ ] manifest.json includes `govcon_mapping` (because all 3 sections included)
- [ ] manifest.json includes `integrity` block (if signing key set)
- [ ] Invalid preset name returns 400 structured error
- [ ] RBAC enforced (non-admin gets 403)
- [ ] Org isolation preserved (cross-org download returns 404)
- [ ] Audit events logged: `preset_requested` + `preset_generated`
- [ ] Statement period filtering works when provided
- [ ] No frontend changes
- [ ] No new Plaid calls
- [ ] No automation introduced

---

## Canonical Laws Compliance

| Requirement | Status |
|-------------|--------|
| Manual execution only | ✅ POST endpoint, no automation |
| No background workers | ✅ In-memory assembly |
| No new Plaid calls | ✅ Uses stored/derived data only |
| RBAC fail-closed | ✅ admin/org:admin required |
| Org isolation | ✅ All queries include organization_id |
| Audit logging | ✅ preset_requested + preset_generated events |
| No compliance claims | ✅ Presets select sections, nothing more |
| No analytics/scoring | ✅ No interpretation of data |
| Strong typing | ✅ `PresetType` enum + `PacketBlock` Pydantic model |
| No frontend changes | ✅ Backend only |
