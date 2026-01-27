# ReconAI Offline Export Verifier

Standalone CLI tool for independently verifying the integrity and provenance of ReconAI Audit Export v2 packages.

## Purpose

This tool allows any third party to verify that an Audit Export v2 ZIP package:

1. Has not been tampered with since generation (file hashes match)
2. Was assembled in the expected deterministic order (hash chain is reproducible)
3. Was signed by the holder of the Ed25519 key (if signing was applied)

## What Is Verified

| Check | Description |
|-------|-------------|
| File hashes | SHA-256 of every file matches the value in `hashes.json` |
| Contents order | Deterministic file ordering hash matches |
| Hash chain | Recomputed chain root matches `manifest.json > integrity > hash_chain > root` |
| Ed25519 signature | Raw signature over the chain root is valid against the included public key |
| Key ID | Public key fingerprint matches `manifest.json > integrity > signature > key_id` |

## What Is NOT Verified

| Not Checked | Explanation |
|-------------|-------------|
| Compliance | This tool does not assess compliance with DCAA, FAR, or any standard |
| Data accuracy | Financial data content is not validated |
| Data completeness | No check that all records are present |
| Authorization | No check that the generator was authorized |
| Certification | This tool does not certify anything |

## Installation

### Prerequisites

- Python 3.9+
- `cryptography` library (for Ed25519 signature verification)

### Install

```bash
cd tools/
pip install -r requirements.txt
```

If verifying unsigned exports (no `signatures/` folder), the `cryptography` library is not required.

## Usage

### 1. Extract the export ZIP

```bash
unzip audit-export-org123-20260127T120000Z.zip -d audit-export-org123
```

### 2. Run the verifier

```bash
python tools/reconai_verify.py ./audit-export-org123
```

### 3. Check the exit code

```bash
echo $?   # Linux/macOS
echo %errorlevel%   # Windows
```

| Exit Code | Meaning |
|-----------|---------|
| `0` | All checks passed |
| `1` | One or more file hashes do not match |
| `2` | Hash chain root does not match expected value |
| `3` | Ed25519 signature verification failed |
| `4` | Malformed package (missing files, bad JSON, etc.) |

## Expected Directory Structure

The verifier expects an extracted directory with this structure:

```
audit-export-{org_id}-{timestamp}/
  statements/
    statements.json
  assets/
    asset_snapshot.json
  liabilities/
    liabilities.json
  signatures/              (only if signing was applied)
    signature.ed25519      (64-byte raw Ed25519 signature)
    public_key.ed25519     (32-byte raw Ed25519 public key)
    signature.json         (signing metadata)
  manifest.json
  hashes.json
```

Not all section folders are required — the verifier checks whatever files are listed in `hashes.json`.

## Example Output

### Signed export (all checks pass)

```
============================================================
  ReconAI Offline Export Verifier
============================================================
  [INFO] Target: /path/to/audit-export-org123-20260127T120000Z
  [INFO] This tool verifies integrity and provenance only.
  [INFO] It does NOT verify compliance, accuracy, or authorization.

============================================================
  Step 0: Package Structure
============================================================
  [PASS] manifest.json loaded (version: v2)
  [PASS] hashes.json loaded (algorithm: SHA-256)
  [INFO] Organization: org123
  [INFO] Generated at: 2026-01-27T12:00:00.000000+00:00
  [INFO] Sections: statements, assets, liabilities
  [INFO] Signing applied: yes

============================================================
  Step 1: File Hash Verification (SHA-256)
============================================================
  [PASS] assets/asset_snapshot.json
  [PASS] liabilities/liabilities.json
  [PASS] manifest.json
  [PASS] signatures/public_key.ed25519
  [PASS] signatures/signature.ed25519
  [PASS] signatures/signature.json
  [PASS] statements/statements.json
  [PASS] contents_order_hash verified
  [INFO] 7 file(s) verified

============================================================
  Step 2: Hash Chain Verification
============================================================
  [PASS] Chain root matches: a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6...

============================================================
  Step 3: Ed25519 Signature Verification
============================================================
  [PASS] Ed25519 signature valid (key_id: a1b2c3d4e5f6a7b8)
  [INFO] Signed at: 2026-01-27T12:00:00.000000+00:00
  [INFO] Algorithm: ed25519

============================================================
  VERDICT: PASS
============================================================

  All checks passed. This export's integrity and provenance
  have been independently verified.

  Verified:
    - File hashes (SHA-256)
    - Deterministic hash chain
    - Ed25519 cryptographic signature

  This verification confirms integrity and provenance ONLY.
  It does NOT constitute compliance certification or data validation.
```

### Unsigned export (signing not applied)

```
============================================================
  Step 2: Hash Chain Verification
============================================================
  [SKIP] No integrity block in manifest (signing was not applied)

============================================================
  Step 3: Ed25519 Signature Verification
============================================================
  [SKIP] No integrity block — signature verification skipped

============================================================
  VERDICT: PASS
============================================================

  All checks passed. This export's integrity and provenance
  have been independently verified.

  Verified:
    - File hashes (SHA-256)
    - No signing was applied (chain/signature checks skipped)
```

### Tampered file (hash mismatch)

```
============================================================
  Step 1: File Hash Verification (SHA-256)
============================================================
  [PASS] assets/asset_snapshot.json
  [FAIL] statements/statements.json
           Expected: a1b2c3...
           Actual:   d4e5f6...

============================================================
  VERDICT: FAIL
============================================================
  [FAIL] One or more file hashes do not match.
```

## How Verification Works

### Hash Chain Construction

The hash chain is built deterministically from section file hashes (sorted by filename):

```
H0 = SHA256(file_1_hash as UTF-8 bytes)
H1 = SHA256(H0_raw_bytes || file_2_hash as UTF-8 bytes)
...
Hn = chain_root (hex string)
```

**Section files** are all files in `hashes.json` EXCEPT `manifest.json` and files under `signatures/`. This matches the builder, which computes the chain before adding manifest and signature hashes.

### Signature Verification

The Ed25519 signature covers `chain_root.encode("utf-8")` — the hex string encoded as UTF-8 bytes. The public key is embedded in the export at `signatures/public_key.ed25519` (raw 32-byte format).

### Key ID

The `key_id` in `manifest.json > integrity > signature > key_id` is the first 16 hex characters of `SHA256(public_key_bytes)`. The verifier recomputes this and cross-checks it.

## Offline Guarantee

This tool:
- Makes zero network calls
- Reads only files within the specified directory
- Has no configuration files or environment variables
- Does not write any files
- Does not require server access
