# app/services/audit_export_builder_v2.py
"""
Audit Export v2 Builder Service

Pure builder/service module for assembling evidence-grade audit export packages.

CANONICAL LAWS:
- No Plaid calls - uses stored/derived data only
- No disk I/O - everything in memory
- No automation - manual execution only
- Deterministic file order for reproducibility
- SHA-256 hashing for all files

Collects:
- Statements PDFs + statements.json (from local database)
- Asset snapshot → assets/asset_snapshot.json (derived from transactions)
- Liabilities → liabilities/liabilities.json (derived from transactions)

Builds:
- manifest.json (v2 format)
- hashes.json (SHA-256 for all files)
"""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.db import get_db_connection


# =============================================================================
# CONSTANTS
# =============================================================================

MANIFEST_VERSION = "v2"
HASH_ALGORITHM = "SHA-256"
EXPORT_TYPE = "audit_export_v2"

COMPLIANCE_NOTES = [
    "This export uses locally stored data only.",
    "No live Plaid API calls were made during export generation.",
    "For authoritative financial data, use the respective Plaid product endpoints.",
]

DATA_SOURCES = {
    "statements": "local_database",
    "assets": "derived_from_transactions",
    "liabilities": "derived_from_transactions",
}


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass(frozen=True)
class StatementData:
    """Statement data from local storage."""
    statement_id: int
    source: str
    total: float
    currency: str
    created_at: str
    raw_data: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class ReceiptData:
    """Receipt data from local storage."""
    receipt_id: int
    source: str
    total: float
    currency: str
    created_at: str
    raw_data: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class AccountSummary:
    """Account summary derived from transactions."""
    account_id: Optional[str]
    transaction_count: int
    total_credits: float
    total_debits: float
    derived_balance: float
    last_transaction_date: Optional[str]


@dataclass(frozen=True)
class BuildResult:
    """Result of building an audit export."""
    zip_buffer: io.BytesIO
    manifest: Dict[str, Any]
    file_hashes: Dict[str, str]
    filename: str


# =============================================================================
# HASH UTILITIES
# =============================================================================

def compute_sha256(data: bytes) -> str:
    """
    Compute SHA-256 hash of binary data.

    Args:
        data: Binary data to hash

    Returns:
        Lowercase hex string of the hash
    """
    return hashlib.sha256(data).hexdigest()


def compute_sha256_str(data: str) -> str:
    """
    Compute SHA-256 hash of string data.

    Args:
        data: String data to hash (UTF-8 encoded)

    Returns:
        Lowercase hex string of the hash
    """
    return compute_sha256(data.encode("utf-8"))


# =============================================================================
# DATA RETRIEVAL (NO PLAID CALLS - LOCAL DATA ONLY)
# =============================================================================

def get_stored_statements(organization_id: str) -> Tuple[List[StatementData], int]:
    """
    Retrieve stored statement records from the database.

    NO PLAID CALLS - uses locally stored data only.

    Args:
        organization_id: Organization to retrieve statements for

    Returns:
        Tuple of (statements_list, count)
    """
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT
                statement_id,
                organization_id,
                source,
                total,
                currency,
                raw_json,
                created_at
            FROM statements
            WHERE organization_id = ?
            ORDER BY created_at DESC
            """,
            (organization_id,)
        )
        rows = cursor.fetchall()

        statements = []
        for row in rows:
            raw_data = None
            if row["raw_json"]:
                try:
                    raw_data = json.loads(row["raw_json"])
                except (json.JSONDecodeError, TypeError):
                    pass

            statements.append(StatementData(
                statement_id=row["statement_id"],
                source=row["source"],
                total=row["total"],
                currency=row["currency"],
                created_at=row["created_at"],
                raw_data=raw_data,
            ))

        return statements, len(statements)

    finally:
        conn.close()


def get_stored_receipts(organization_id: str) -> Tuple[List[ReceiptData], int]:
    """
    Retrieve stored receipt records from the database.

    NO PLAID CALLS - uses locally stored data only.

    Args:
        organization_id: Organization to retrieve receipts for

    Returns:
        Tuple of (receipts_list, count)
    """
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT
                receipt_id,
                organization_id,
                source,
                total,
                currency,
                raw_json,
                created_at
            FROM receipts
            WHERE organization_id = ?
            ORDER BY created_at DESC
            """,
            (organization_id,)
        )
        rows = cursor.fetchall()

        receipts = []
        for row in rows:
            raw_data = None
            if row["raw_json"]:
                try:
                    raw_data = json.loads(row["raw_json"])
                except (json.JSONDecodeError, TypeError):
                    pass

            receipts.append(ReceiptData(
                receipt_id=row["receipt_id"],
                source=row["source"],
                total=row["total"],
                currency=row["currency"],
                created_at=row["created_at"],
                raw_data=raw_data,
            ))

        return receipts, len(receipts)

    finally:
        conn.close()


def derive_asset_snapshot(organization_id: str) -> Dict[str, Any]:
    """
    Derive asset snapshot from stored transaction data.

    NO PLAID CALLS - uses locally stored/derived data only.

    Args:
        organization_id: Organization to derive assets for

    Returns:
        Asset snapshot dictionary with accounts, totals, and metadata
    """
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT
                account_id,
                COUNT(*) as transaction_count,
                SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) as total_credits,
                SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END) as total_debits,
                MAX(date) as last_transaction_date
            FROM core_transactions
            WHERE organization_id = ?
            GROUP BY account_id
            """,
            (organization_id,)
        )
        rows = cursor.fetchall()

        accounts = []
        total_assets = 0.0

        for row in rows:
            net_balance = (row["total_credits"] or 0) - (row["total_debits"] or 0)
            accounts.append({
                "account_id": row["account_id"],
                "transaction_count": row["transaction_count"],
                "total_credits": round(row["total_credits"] or 0, 2),
                "total_debits": round(row["total_debits"] or 0, 2),
                "derived_balance": round(net_balance, 2),
                "last_transaction_date": row["last_transaction_date"],
            })
            if net_balance > 0:
                total_assets += net_balance

        return {
            "snapshot_type": "derived_from_transactions",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "accounts": accounts,
            "accounts_count": len(accounts),
            "total_assets_derived": round(total_assets, 2),
            "disclaimer": (
                "This snapshot is derived from stored transaction data. "
                "It does not represent a live balance or official Plaid Asset Report. "
                "For authoritative asset data, generate a Plaid Asset Report via the assets/report/create endpoint."
            ),
            "label": "Derived Asset Summary (from stored transactions)",
        }

    finally:
        conn.close()


def derive_liabilities_snapshot(organization_id: str) -> Dict[str, Any]:
    """
    Derive liabilities snapshot from stored transaction data.

    NO PLAID CALLS - uses locally stored/derived data only.

    Args:
        organization_id: Organization to derive liabilities for

    Returns:
        Liabilities snapshot dictionary with accounts, totals, and metadata
    """
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT
                account_id,
                COUNT(*) as transaction_count,
                SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) as total_credits,
                SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END) as total_debits,
                MAX(date) as last_transaction_date
            FROM core_transactions
            WHERE organization_id = ?
            GROUP BY account_id
            HAVING (SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) -
                    SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END)) < 0
            """,
            (organization_id,)
        )
        rows = cursor.fetchall()

        liability_accounts = []
        total_liabilities = 0.0

        for row in rows:
            net_balance = (row["total_credits"] or 0) - (row["total_debits"] or 0)
            liability_accounts.append({
                "account_id": row["account_id"],
                "transaction_count": row["transaction_count"],
                "total_credits": round(row["total_credits"] or 0, 2),
                "total_debits": round(row["total_debits"] or 0, 2),
                "derived_balance": round(net_balance, 2),
                "last_transaction_date": row["last_transaction_date"],
            })
            total_liabilities += abs(net_balance)

        return {
            "snapshot_type": "derived_from_transactions",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "credit_cards": [],  # Not derivable without Plaid liabilities call
            "student_loans": [],
            "mortgages": [],
            "other_loans": [],
            "derived_liability_accounts": liability_accounts,
            "derived_liability_count": len(liability_accounts),
            "total_liabilities_derived": round(total_liabilities, 2),
            "disclaimer": (
                "This snapshot is derived from stored transaction data. "
                "It does not represent official Plaid Liabilities data. "
                "For authoritative liability data, use the liabilities/get endpoint."
            ),
            "label": "Derived Liabilities Summary (from stored transactions)",
        }

    finally:
        conn.close()


# =============================================================================
# SECTION BUILDERS
# =============================================================================

def build_statements_section(
    organization_id: str,
    generated_at_iso: str,
) -> Tuple[bytes, Dict[str, int]]:
    """
    Build the statements section JSON.

    Args:
        organization_id: Organization ID
        generated_at_iso: Generation timestamp (ISO format)

    Returns:
        Tuple of (json_bytes, counts_dict)
    """
    statements, stmt_count = get_stored_statements(organization_id)
    receipts, receipt_count = get_stored_receipts(organization_id)

    # Convert dataclasses to dicts
    statements_list = [
        {
            "statement_id": s.statement_id,
            "source": s.source,
            "total": s.total,
            "currency": s.currency,
            "created_at": s.created_at,
            "raw_data": s.raw_data,
        }
        for s in statements
    ]

    receipts_list = [
        {
            "receipt_id": r.receipt_id,
            "source": r.source,
            "total": r.total,
            "currency": r.currency,
            "created_at": r.created_at,
            "raw_data": r.raw_data,
        }
        for r in receipts
    ]

    data = {
        "organization_id": organization_id,
        "generated_at": generated_at_iso,
        "statements": statements_list,
        "statements_count": stmt_count,
        "receipts": receipts_list,
        "receipts_count": receipt_count,
        "data_source": "local_database",
        "disclaimer": "Statement data from local storage. PDFs not included in this export.",
    }

    json_bytes = json.dumps(data, indent=2, default=str).encode("utf-8")
    counts = {"statements": stmt_count, "receipts": receipt_count}

    return json_bytes, counts


def build_assets_section(organization_id: str) -> Tuple[bytes, int]:
    """
    Build the assets section JSON.

    Args:
        organization_id: Organization ID

    Returns:
        Tuple of (json_bytes, accounts_count)
    """
    snapshot = derive_asset_snapshot(organization_id)
    json_bytes = json.dumps(snapshot, indent=2, default=str).encode("utf-8")
    return json_bytes, snapshot.get("accounts_count", 0)


def build_liabilities_section(organization_id: str) -> Tuple[bytes, int]:
    """
    Build the liabilities section JSON.

    Args:
        organization_id: Organization ID

    Returns:
        Tuple of (json_bytes, accounts_count)
    """
    snapshot = derive_liabilities_snapshot(organization_id)
    json_bytes = json.dumps(snapshot, indent=2, default=str).encode("utf-8")
    return json_bytes, snapshot.get("derived_liability_count", 0)


# =============================================================================
# MANIFEST AND HASHES BUILDERS
# =============================================================================

def build_manifest(
    org_id: str,
    user_id: str,
    request_id: str,
    generated_at_iso: str,
    included_sections: List[str],
    counts: Dict[str, int],
    files: List[str],
) -> bytes:
    """
    Build the manifest.json content.

    Args:
        org_id: Organization ID
        user_id: User who generated the export
        request_id: Request trace identifier
        generated_at_iso: Generation timestamp (ISO format)
        included_sections: List of included section names
        counts: Per-section counts
        files: List of files in the export

    Returns:
        JSON bytes for manifest.json
    """
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "org_id": org_id,
        "generated_at": generated_at_iso,
        "generated_by": user_id,
        "request_id": request_id,
        "included_sections": included_sections,
        "counts": counts,
        "files": files,
        "export_type": EXPORT_TYPE,
        "data_sources": DATA_SOURCES,
        "compliance_notes": COMPLIANCE_NOTES,
    }

    return json.dumps(manifest, indent=2, default=str).encode("utf-8")


def build_hashes(
    generated_at_iso: str,
    file_hashes: Dict[str, str],
) -> bytes:
    """
    Build the hashes.json content.

    Args:
        generated_at_iso: Generation timestamp (ISO format)
        file_hashes: Dictionary of file paths to their SHA-256 hashes

    Returns:
        JSON bytes for hashes.json
    """
    # Compute hash of logical contents order (deterministic)
    sorted_files = sorted(file_hashes.keys())
    contents_order_str = json.dumps(sorted_files, sort_keys=True)
    contents_order_hash = compute_sha256_str(contents_order_str)

    hashes_data = {
        "generated_at": generated_at_iso,
        "algorithm": HASH_ALGORITHM,
        "file_hashes": file_hashes,
        "contents_order": sorted_files,
        "contents_order_hash": contents_order_hash,
    }

    return json.dumps(hashes_data, indent=2, default=str).encode("utf-8")


# =============================================================================
# MAIN BUILDER
# =============================================================================

def build_audit_export_v2(
    organization_id: str,
    user_id: str,
    request_id: str,
    include_statements: bool = True,
    include_assets: bool = True,
    include_liabilities: bool = True,
) -> BuildResult:
    """
    Build the complete audit export v2 ZIP package.

    NO TEMP FILES - everything assembled in memory.
    NO PLAID CALLS - uses stored/derived data only.
    DETERMINISTIC - file order is sorted for reproducibility.

    Args:
        organization_id: Organization to export data for
        user_id: User generating the export
        request_id: Request trace identifier
        include_statements: Include statements section
        include_assets: Include assets section
        include_liabilities: Include liabilities section

    Returns:
        BuildResult with zip_buffer, manifest, file_hashes, and filename
    """
    generated_at = datetime.now(timezone.utc)
    generated_at_iso = generated_at.isoformat()

    # Track all file contents and their hashes
    file_contents: Dict[str, bytes] = {}
    file_hashes: Dict[str, str] = {}
    included_sections: List[str] = []
    section_counts: Dict[str, int] = {}

    # ==========================================================================
    # STATEMENTS SECTION
    # ==========================================================================
    if include_statements:
        stmt_json, stmt_counts = build_statements_section(organization_id, generated_at_iso)
        file_contents["statements/statements.json"] = stmt_json
        file_hashes["statements/statements.json"] = compute_sha256(stmt_json)
        included_sections.append("statements")
        section_counts.update(stmt_counts)

    # ==========================================================================
    # ASSETS SECTION
    # ==========================================================================
    if include_assets:
        assets_json, assets_count = build_assets_section(organization_id)
        file_contents["assets/asset_snapshot.json"] = assets_json
        file_hashes["assets/asset_snapshot.json"] = compute_sha256(assets_json)
        included_sections.append("assets")
        section_counts["assets_accounts"] = assets_count

    # ==========================================================================
    # LIABILITIES SECTION
    # ==========================================================================
    if include_liabilities:
        liab_json, liab_count = build_liabilities_section(organization_id)
        file_contents["liabilities/liabilities.json"] = liab_json
        file_hashes["liabilities/liabilities.json"] = compute_sha256(liab_json)
        included_sections.append("liabilities")
        section_counts["liabilities_accounts"] = liab_count

    # ==========================================================================
    # MANIFEST
    # ==========================================================================
    manifest_json = build_manifest(
        org_id=organization_id,
        user_id=user_id,
        request_id=request_id,
        generated_at_iso=generated_at_iso,
        included_sections=included_sections,
        counts=section_counts,
        files=list(file_contents.keys()),
    )
    file_contents["manifest.json"] = manifest_json
    file_hashes["manifest.json"] = compute_sha256(manifest_json)

    # ==========================================================================
    # HASHES (including manifest hash)
    # ==========================================================================
    hashes_json = build_hashes(generated_at_iso, file_hashes)
    file_contents["hashes.json"] = hashes_json
    # Note: hashes.json itself is not included in file_hashes to avoid circular dependency

    # ==========================================================================
    # BUILD ZIP
    # ==========================================================================
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as zf:
        # Write files in deterministic (sorted) order
        for filepath in sorted(file_contents.keys()):
            zf.writestr(filepath, file_contents[filepath])

    mem.seek(0)

    # Generate deterministic filename
    timestamp_str = generated_at.strftime("%Y%m%dT%H%M%SZ")
    filename = f"audit-export-{organization_id}-{timestamp_str}.zip"

    # Parse manifest for return
    manifest_data = json.loads(manifest_json.decode("utf-8"))

    return BuildResult(
        zip_buffer=mem,
        manifest=manifest_data,
        file_hashes=file_hashes,
        filename=filename,
    )


# =============================================================================
# PREVIEW BUILDER
# =============================================================================

def get_export_preview(organization_id: str) -> Dict[str, Any]:
    """
    Get a preview of what would be included in an audit export.

    NO ZIP GENERATION - just counts and metadata.
    NO PLAID CALLS - uses stored/derived data only.

    Args:
        organization_id: Organization to preview

    Returns:
        Dictionary with available data summary
    """
    statements, stmt_count = get_stored_statements(organization_id)
    receipts, receipt_count = get_stored_receipts(organization_id)
    asset_snapshot = derive_asset_snapshot(organization_id)
    liabilities_snapshot = derive_liabilities_snapshot(organization_id)

    return {
        "organization_id": organization_id,
        "preview_generated_at": datetime.now(timezone.utc).isoformat(),
        "available_data": {
            "statements": {
                "count": stmt_count,
                "receipts_count": receipt_count,
                "data_source": "local_database",
            },
            "assets": {
                "accounts_count": asset_snapshot.get("accounts_count", 0),
                "total_assets_derived": asset_snapshot.get("total_assets_derived", 0),
                "data_source": "derived_from_transactions",
            },
            "liabilities": {
                "derived_accounts_count": liabilities_snapshot.get("derived_liability_count", 0),
                "total_liabilities_derived": liabilities_snapshot.get("total_liabilities_derived", 0),
                "data_source": "derived_from_transactions",
            },
        },
        "export_structure": [
            "statements/statements.json",
            "assets/asset_snapshot.json",
            "liabilities/liabilities.json",
            "manifest.json",
            "hashes.json",
        ],
        "notes": COMPLIANCE_NOTES,
    }
