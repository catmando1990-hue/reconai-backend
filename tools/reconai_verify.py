#!/usr/bin/env python3
"""
ReconAI Offline Export Verifier (Phase 13A)

Standalone CLI tool for independently verifying the integrity and provenance
of Audit Export v2 packages. Operates fully offline — no network calls,
no server dependencies.

WHAT THIS TOOL VERIFIES:
    - SHA-256 file hashes match expected values
    - Deterministic hash chain root is reproducible
    - Ed25519 signature is valid (if signing was applied)

WHAT THIS TOOL DOES NOT VERIFY:
    - Compliance with any standard (DCAA, FAR, etc.)
    - Accuracy or completeness of financial data
    - Authorization of the export generator

EXIT CODES:
    0 — All checks passed
    1 — File hash mismatch
    2 — Hash chain root mismatch
    3 — Ed25519 signature invalid
    4 — Malformed package (missing files, bad JSON, etc.)
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# =============================================================================
# EXIT CODES
# =============================================================================

EXIT_SUCCESS = 0
EXIT_HASH_MISMATCH = 1
EXIT_CHAIN_MISMATCH = 2
EXIT_SIGNATURE_INVALID = 3
EXIT_MALFORMED = 4


# =============================================================================
# DISPLAY HELPERS
# =============================================================================

def print_header(text: str) -> None:
    """Print a section header."""
    print(f"\n{'=' * 60}")
    print(f"  {text}")
    print(f"{'=' * 60}")


def print_pass(text: str) -> None:
    """Print a passing check."""
    print(f"  [PASS] {text}")


def print_fail(text: str) -> None:
    """Print a failing check."""
    print(f"  [FAIL] {text}")


def print_skip(text: str) -> None:
    """Print a skipped check."""
    print(f"  [SKIP] {text}")


def print_info(text: str) -> None:
    """Print an informational line."""
    print(f"  [INFO] {text}")


# =============================================================================
# SHA-256 UTILITIES
# =============================================================================

def compute_sha256(data: bytes) -> str:
    """Compute SHA-256 hash, returning lowercase hex string."""
    return hashlib.sha256(data).hexdigest()


def compute_sha256_file(filepath: Path) -> str:
    """Compute SHA-256 hash of a file."""
    return compute_sha256(filepath.read_bytes())


# =============================================================================
# HASH CHAIN (must match builder exactly)
# =============================================================================

def compute_hash_chain(ordered_file_hashes: List[Tuple[str, str]]) -> str:
    """
    Compute a deterministic hash chain over sorted file hashes.

    Chain construction (must match audit_export_builder_v2.py exactly):
        H0 = SHA256(file_1_hash as UTF-8 bytes)
        H1 = SHA256(H0_digest_bytes || file_2_hash as UTF-8 bytes)
        ...
        Hn = chain_root (hex string)

    Args:
        ordered_file_hashes: Sorted list of (filename, sha256_hex) tuples

    Returns:
        Final chain root as lowercase hex string
    """
    if not ordered_file_hashes:
        return compute_sha256(b"empty")

    # H0 = SHA256(first file hash encoded as UTF-8)
    chain = hashlib.sha256(ordered_file_hashes[0][1].encode("utf-8")).digest()

    # Iterate remaining: Hn = SHA256(Hn-1_digest || file_n_hash_utf8)
    for _, file_hash in ordered_file_hashes[1:]:
        chain = hashlib.sha256(chain + file_hash.encode("utf-8")).digest()

    return chain.hex()


# =============================================================================
# ED25519 SIGNATURE VERIFICATION
# =============================================================================

def verify_ed25519(
    chain_root: str,
    signature_bytes: bytes,
    public_key_bytes: bytes,
) -> bool:
    """
    Verify Ed25519 signature over the chain root.

    The signature covers chain_root.encode("utf-8") — the hex string
    as UTF-8 bytes, matching the builder's signing logic.

    Args:
        chain_root: Hex-encoded chain root that was signed
        signature_bytes: Raw 64-byte Ed25519 signature
        public_key_bytes: Raw 32-byte Ed25519 public key

    Returns:
        True if signature is valid, False otherwise
    """
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
        public_key.verify(signature_bytes, chain_root.encode("utf-8"))
        return True
    except ImportError:
        print_fail("cryptography library not installed. Run: pip install cryptography>=42.0.0")
        return False
    except Exception:
        return False


# =============================================================================
# PACKAGE VALIDATION
# =============================================================================

def load_json_file(filepath: Path) -> Optional[Dict[str, Any]]:
    """Load and parse a JSON file. Returns None on failure."""
    try:
        return json.loads(filepath.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print_fail(f"Cannot read {filepath.name}: {e}")
        return None


def validate_package_structure(export_dir: Path) -> Optional[Tuple[Dict, Dict]]:
    """
    Validate the basic package structure.

    Returns (manifest, hashes) dicts or None if malformed.
    """
    manifest_path = export_dir / "manifest.json"
    hashes_path = export_dir / "hashes.json"

    if not manifest_path.exists():
        print_fail("manifest.json not found")
        return None

    if not hashes_path.exists():
        print_fail("hashes.json not found")
        return None

    manifest = load_json_file(manifest_path)
    if manifest is None:
        return None

    hashes = load_json_file(hashes_path)
    if hashes is None:
        return None

    # Validate manifest has required fields
    required_manifest = ["manifest_version", "org_id", "generated_at", "included_sections"]
    for field in required_manifest:
        if field not in manifest:
            print_fail(f"manifest.json missing required field: {field}")
            return None

    # Validate hashes has required fields
    required_hashes = ["algorithm", "file_hashes", "contents_order"]
    for field in required_hashes:
        if field not in hashes:
            print_fail(f"hashes.json missing required field: {field}")
            return None

    if hashes["algorithm"] != "SHA-256":
        print_fail(f"Unsupported hash algorithm: {hashes['algorithm']} (expected SHA-256)")
        return None

    return manifest, hashes


# =============================================================================
# STEP 1: FILE HASH VERIFICATION
# =============================================================================

def verify_file_hashes(export_dir: Path, hashes_data: Dict) -> Tuple[bool, Dict[str, str]]:
    """
    Verify SHA-256 hashes for all files listed in hashes.json.

    Returns:
        (all_passed, computed_hashes_dict)
    """
    file_hashes = hashes_data["file_hashes"]
    all_passed = True
    computed: Dict[str, str] = {}
    missing_files: List[str] = []
    mismatched: List[str] = []

    for filename, expected_hash in sorted(file_hashes.items()):
        filepath = export_dir / filename
        if not filepath.exists():
            print_fail(f"Missing file: {filename}")
            missing_files.append(filename)
            all_passed = False
            continue

        actual_hash = compute_sha256_file(filepath)
        computed[filename] = actual_hash

        if actual_hash == expected_hash:
            print_pass(f"{filename}")
        else:
            print_fail(f"{filename}")
            print(f"           Expected: {expected_hash}")
            print(f"           Actual:   {actual_hash}")
            mismatched.append(filename)
            all_passed = False

    # Check for extra files in hashes.json that aren't on disk
    if missing_files:
        print_info(f"{len(missing_files)} file(s) listed in hashes.json but missing from package")

    if mismatched:
        print_info(f"{len(mismatched)} file(s) have hash mismatches")

    return all_passed, computed


# =============================================================================
# STEP 2: HASH CHAIN VERIFICATION
# =============================================================================

def verify_hash_chain(
    manifest: Dict,
    hashes_data: Dict,
    computed_hashes: Dict[str, str],
) -> Tuple[bool, Optional[str]]:
    """
    Rebuild the deterministic hash chain and compare to manifest.

    The chain covers SECTION files only (not manifest.json, not signatures/*).
    This matches the builder, which computes the chain before adding manifest
    and signature hashes.

    Returns:
        (chain_matches, computed_chain_root)
    """
    integrity = manifest.get("integrity")
    if integrity is None:
        print_skip("No integrity block in manifest (signing was not applied)")
        return True, None

    expected_root = integrity.get("hash_chain", {}).get("root")
    if not expected_root:
        print_fail("integrity block missing hash_chain.root")
        return False, None

    # Identify section files: everything in file_hashes EXCEPT manifest.json
    # and signatures/* — those are added AFTER chain computation in the builder.
    file_hashes = hashes_data["file_hashes"]
    section_hashes: List[Tuple[str, str]] = []

    for filename, hash_val in file_hashes.items():
        if filename == "manifest.json":
            continue
        if filename.startswith("signatures/"):
            continue
        # Use the computed hash (verified in Step 1) if available,
        # otherwise fall back to hashes.json value
        actual_hash = computed_hashes.get(filename, hash_val)
        section_hashes.append((filename, actual_hash))

    # Sort deterministically (same as builder: sorted(file_hashes.items()))
    section_hashes.sort()

    computed_root = compute_hash_chain(section_hashes)

    if computed_root == expected_root:
        print_pass(f"Chain root matches: {computed_root[:32]}...")
        return True, computed_root
    else:
        print_fail("Chain root mismatch")
        print(f"           Expected: {expected_root}")
        print(f"           Computed: {computed_root}")
        print_info(f"Chain computed over {len(section_hashes)} section file(s):")
        for fname, _ in section_hashes:
            print(f"             - {fname}")
        return False, computed_root


# =============================================================================
# STEP 3: ED25519 SIGNATURE VERIFICATION
# =============================================================================

def verify_signature(
    export_dir: Path,
    manifest: Dict,
    chain_root: Optional[str],
) -> bool:
    """
    Verify the Ed25519 signature using the included public key.

    Returns True if signature is valid or signing was not applied.
    """
    integrity = manifest.get("integrity")
    if integrity is None:
        print_skip("No integrity block — signature verification skipped")
        return True

    sig_path = export_dir / "signatures" / "signature.ed25519"
    pub_path = export_dir / "signatures" / "public_key.ed25519"
    meta_path = export_dir / "signatures" / "signature.json"

    if not sig_path.exists():
        print_fail("signatures/signature.ed25519 not found")
        return False

    if not pub_path.exists():
        print_fail("signatures/public_key.ed25519 not found")
        return False

    signature_bytes = sig_path.read_bytes()
    public_key_bytes = pub_path.read_bytes()

    # Validate sizes
    if len(signature_bytes) != 64:
        print_fail(f"Signature file is {len(signature_bytes)} bytes (expected 64)")
        return False

    if len(public_key_bytes) != 32:
        print_fail(f"Public key file is {len(public_key_bytes)} bytes (expected 32)")
        return False

    # Use chain root from manifest integrity block
    expected_root = integrity.get("hash_chain", {}).get("root", "")

    # Prefer the chain root we computed (verified in Step 2)
    root_to_verify = chain_root if chain_root else expected_root

    # Verify Ed25519 signature
    if verify_ed25519(root_to_verify, signature_bytes, public_key_bytes):
        # Cross-check key_id
        key_id_expected = integrity.get("signature", {}).get("key_id", "")
        key_id_computed = compute_sha256(public_key_bytes)[:16]

        if key_id_expected and key_id_computed != key_id_expected:
            print_fail(f"key_id mismatch: expected {key_id_expected}, computed {key_id_computed}")
            return False

        print_pass(f"Ed25519 signature valid (key_id: {key_id_computed})")

        # Print signature metadata if available
        if meta_path.exists():
            meta = load_json_file(meta_path)
            if meta:
                print_info(f"Signed at: {meta.get('signed_at', 'unknown')}")
                print_info(f"Algorithm: {meta.get('algorithm', 'unknown')}")

        return True
    else:
        print_fail("Ed25519 signature verification FAILED")
        return False


# =============================================================================
# MAIN VERIFICATION PIPELINE
# =============================================================================

def verify_export(export_dir: Path) -> int:
    """
    Run the full verification pipeline on an extracted export directory.

    Returns exit code (0=success, 1-4=failure type).
    """
    print_header("ReconAI Offline Export Verifier")
    print_info(f"Target: {export_dir}")
    print_info("This tool verifies integrity and provenance only.")
    print_info("It does NOT verify compliance, accuracy, or authorization.")

    # =========================================================================
    # VALIDATE PACKAGE STRUCTURE
    # =========================================================================
    print_header("Step 0: Package Structure")

    if not export_dir.is_dir():
        print_fail(f"Not a directory: {export_dir}")
        return EXIT_MALFORMED

    result = validate_package_structure(export_dir)
    if result is None:
        print_fail("Package structure validation failed")
        return EXIT_MALFORMED

    manifest, hashes_data = result
    print_pass(f"manifest.json loaded (version: {manifest.get('manifest_version', '?')})")
    print_pass(f"hashes.json loaded (algorithm: {hashes_data.get('algorithm', '?')})")
    print_info(f"Organization: {manifest.get('org_id', '?')}")
    print_info(f"Generated at: {manifest.get('generated_at', '?')}")
    print_info(f"Sections: {', '.join(manifest.get('included_sections', []))}")

    has_signing = manifest.get("integrity") is not None
    print_info(f"Signing applied: {'yes' if has_signing else 'no'}")

    has_packet = manifest.get("packet") is not None
    if has_packet:
        print_info(f"Preset: {manifest['packet'].get('preset', '?')}")

    # =========================================================================
    # STEP 1: FILE HASHES
    # =========================================================================
    print_header("Step 1: File Hash Verification (SHA-256)")

    hashes_ok, computed_hashes = verify_file_hashes(export_dir, hashes_data)

    # Also verify hashes.json contents_order_hash
    contents_order = hashes_data.get("contents_order", [])
    expected_order_hash = hashes_data.get("contents_order_hash", "")
    if contents_order and expected_order_hash:
        computed_order_hash = compute_sha256(
            json.dumps(contents_order, sort_keys=True).encode("utf-8")
        )
        if computed_order_hash == expected_order_hash:
            print_pass("contents_order_hash verified")
        else:
            print_fail("contents_order_hash mismatch")
            hashes_ok = False

    if not hashes_ok:
        print_header("VERDICT: FAIL")
        print_fail("One or more file hashes do not match.")
        return EXIT_HASH_MISMATCH

    total_files = len(hashes_data.get("file_hashes", {}))
    print_info(f"{total_files} file(s) verified")

    # =========================================================================
    # STEP 2: HASH CHAIN
    # =========================================================================
    print_header("Step 2: Hash Chain Verification")

    chain_ok, computed_root = verify_hash_chain(manifest, hashes_data, computed_hashes)

    if not chain_ok:
        print_header("VERDICT: FAIL")
        print_fail("Hash chain root does not match expected value.")
        return EXIT_CHAIN_MISMATCH

    # =========================================================================
    # STEP 3: ED25519 SIGNATURE
    # =========================================================================
    print_header("Step 3: Ed25519 Signature Verification")

    sig_ok = verify_signature(export_dir, manifest, computed_root)

    if not sig_ok:
        print_header("VERDICT: FAIL")
        print_fail("Ed25519 signature verification failed.")
        return EXIT_SIGNATURE_INVALID

    # =========================================================================
    # FINAL VERDICT
    # =========================================================================
    print_header("VERDICT: PASS")
    print()
    print("  All checks passed. This export's integrity and provenance")
    print("  have been independently verified.")
    print()
    if has_signing:
        print("  Verified:")
        print("    - File hashes (SHA-256)")
        print("    - Deterministic hash chain")
        print("    - Ed25519 cryptographic signature")
    else:
        print("  Verified:")
        print("    - File hashes (SHA-256)")
        print("    - No signing was applied (chain/signature checks skipped)")
    print()
    print("  This verification confirms integrity and provenance ONLY.")
    print("  It does NOT constitute compliance certification or data validation.")
    print()

    return EXIT_SUCCESS


# =============================================================================
# CLI ENTRY POINT
# =============================================================================

def main() -> None:
    """CLI entry point."""
    if len(sys.argv) != 2:
        print("Usage: reconai-verify <export-directory>")
        print()
        print("  Verifies the integrity and provenance of an extracted")
        print("  ReconAI Audit Export v2 package.")
        print()
        print("  Example:")
        print("    python reconai_verify.py ./audit-export-org123-20260127T120000Z")
        print()
        print("Exit codes:")
        print("  0  All checks passed")
        print("  1  File hash mismatch")
        print("  2  Hash chain root mismatch")
        print("  3  Ed25519 signature invalid")
        print("  4  Malformed package")
        sys.exit(EXIT_MALFORMED)

    export_path = Path(sys.argv[1]).resolve()
    exit_code = verify_export(export_path)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
