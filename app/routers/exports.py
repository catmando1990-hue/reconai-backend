from __future__ import annotations

# stdlib
import csv
import io
import re
import logging
from datetime import date, datetime
from typing import Iterable, Iterator, List, Optional
from urllib.parse import quote

# fastapi
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# local
from app.models import TransactionsRequest, TransactionsResponse
from app.reconai_core.analysis import analyze_transactions as core_analyze_transactions
from app.auth_context import get_current_context, AuthContext
from app.services.s3_exports import (
    generate_download_url,
    get_export_for_user,
    list_user_exports,
    DEFAULT_URL_EXPIRATION_SECONDS,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/exports", tags=["exports"])

# ----------------------------
# Constants
# ----------------------------

_CSV_HEADER: List[str] = [
    "date",
    "amount",
    "description",
    "merchant",
    "original_category",
    "classification",
    "reason",  # ✅ NEW
]
_DEFAULT_FILENAME = "reconai-export.csv"
_filename_bad_chars = re.compile(r"[^A-Za-z0-9._-]")

# ----------------------------
# Helpers
# ----------------------------


def _iso_date_or_empty(value: Optional[object]) -> str:
    """Why: tolerate date/datetime/str/None without raising."""
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    return str(value)


def _write_rows(writer: csv.writer, rows: Iterable[object], fallback_label: str) -> None:
    """
    Writes rows with Option-2 fields if present:
      - tx.classification
      - tx.reason
    Falls back to provided label if classification missing.
    """
    for tx in rows or []:
        cls = getattr(tx, "classification", None) or fallback_label
        reason = getattr(tx, "reason", None)

        writer.writerow(
            [
                _iso_date_or_empty(getattr(tx, "date", None)),
                getattr(tx, "amount", ""),
                getattr(tx, "description", "") or "",
                getattr(tx, "merchant", "") or "",
                getattr(tx, "original_category", "") or "",
                cls,
                reason or "",
            ]
        )


def _csv_from_response(result: TransactionsResponse, add_bom: bool = False) -> str:
    output = io.StringIO(newline="")
    if add_bom:
        output.write("\ufeff")
    writer = csv.writer(output, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)

    writer.writerow(_CSV_HEADER)
    _write_rows(writer, result.business_expenses, "business")
    _write_rows(writer, result.personal_expenses, "personal")
    _write_rows(writer, getattr(result, "transfers", []), "transfer")
    _write_rows(writer, result.uncertain, "uncertain")

    return output.getvalue()


def _iter_csv(result: TransactionsResponse, add_bom: bool = False) -> Iterator[str]:
    """Why: stream for large datasets to reduce memory peak."""
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)

    if add_bom:
        yield "\ufeff"

    writer.writerow(_CSV_HEADER)
    data = buf.getvalue()
    if data:
        yield data
    buf.seek(0)
    buf.truncate(0)

    def flush_rows(rows: Iterable[object], label: str) -> Iterator[str]:
        _write_rows(writer, rows, label)
        chunk = buf.getvalue()
        if chunk:
            yield chunk
        buf.seek(0)
        buf.truncate(0)

    yield from flush_rows(result.business_expenses, "business")
    yield from flush_rows(result.personal_expenses, "personal")
    yield from flush_rows(getattr(result, "transfers", []), "transfer")
    yield from flush_rows(result.uncertain, "uncertain")


def _sanitize_filename(name: Optional[str]) -> str:
    """Why: prevent header injection/illegal paths; keep it predictable."""
    if not name:
        return _DEFAULT_FILENAME
    name = name.strip()
    name = name.replace("\r", "_").replace("\n", "_")  # readability + safety
    name = _filename_bad_chars.sub("_", name)  # replace other bad chars

    # NOTE: keep behavior consistent with your existing tests/expectations:
    # do NOT collapse multiple underscores.
    if not name:
        name = "export.csv"
    if not name.lower().endswith(".csv"):
        name += ".csv"
    if len(name) > 128:
        root, dot, ext = name.rpartition(".")
        root = root or name
        ext = ext or "csv"
        name = root[:100] + "." + ext
    return name


def _ascii_fallback(name: str) -> str:
    """Why: some UAs ignore filename*; provide safe ASCII."""
    try:
        name.encode("ascii")
        return name
    except UnicodeEncodeError:
        return "".join(ch if ord(ch) < 128 else "_" for ch in name)


def _disposition_header(filename: str) -> str:
    """
    RFC 5987-style: include both filename and filename* for UTF-8.
    Keeps simple ASCII fallback to maximize compatibility.
    """
    safe_ascii = _ascii_fallback(filename)
    utf8_pct = quote(filename.encode("utf-8"))
    return f'attachment; filename="{safe_ascii}"; filename*=UTF-8\'\'{utf8_pct}'


# ----------------------------
# Endpoints
# ----------------------------

@router.post("/csv")
def export_csv(
    payload: TransactionsResponse,
    excel: bool = Query(False, description="If true, add UTF-8 BOM for Excel"),
    filename: Optional[str] = Query(None, description="Override download filename"),
):
    """Export already-analyzed transactions to CSV."""
    safe_name = _sanitize_filename(filename)
    return StreamingResponse(
        _iter_csv(payload, add_bom=excel),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": _disposition_header(safe_name)},
    )


@router.post("/json", response_model=TransactionsResponse)
def export_json(payload: TransactionsResponse):
    """Echo analyzed JSON for download or frontend save."""
    return payload


@router.post("/csv-from-input")
def export_csv_from_input(
    payload: TransactionsRequest = Body(..., description="Raw transactions input"),
    excel: bool = Query(False, description="If true, add UTF-8 BOM for Excel"),
    filename: Optional[str] = Query(None, description="Override download filename"),
):
    """Analyze raw input and export CSV in one step."""
    result = core_analyze_transactions(payload)
    safe_name = _sanitize_filename(filename)
    return StreamingResponse(
        _iter_csv(result, add_bom=excel),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": _disposition_header(safe_name)},
    )


@router.post("/json-from-input", response_model=TransactionsResponse)
def export_json_from_input(
    payload: TransactionsRequest = Body(..., description="Raw transactions input"),
):
    """Analyze raw input and return JSON."""
    return core_analyze_transactions(payload)


# ----------------------------
# S3 Export Models
# ----------------------------

class S3ExportDownloadResponse(BaseModel):
    """Response model for signed download URL."""
    download_url: str
    expires_in_seconds: int = DEFAULT_URL_EXPIRATION_SECONDS


class S3ExportListResponse(BaseModel):
    """Response model for listing exports."""
    exports: List[dict]
    total: int


# ----------------------------
# S3 Export Endpoints
# ----------------------------
# NOTE: Upload functionality (upload_export) is internal-only.
# It is called by backend export generation flows, not exposed as public API.
# This follows ReconAI laws: Manual-only intelligence, backend-owned artifacts.


@router.get("/{export_id}/download", response_model=S3ExportDownloadResponse)
async def get_export_download_url(
    export_id: str,
    expires_seconds: int = Query(
        default=DEFAULT_URL_EXPIRATION_SECONDS,
        ge=60,
        le=3600,
        description="URL expiration time in seconds (60-3600)",
    ),
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Get a signed download URL for an export.

    The signed URL provides time-limited access to the private S3 object.
    Default expiration is 300 seconds (5 minutes).

    Requirements:
    - User must be authenticated
    - User must own the export (same user_id and org_id)

    Returns:
    - download_url: Presigned S3 URL for download
    - expires_in_seconds: URL expiration time
    """
    from botocore.exceptions import ClientError, NoCredentialsError

    user_id = ctx["user_id"]
    org_id = ctx["org_id"]

    # Look up export and validate ownership
    export_record = get_export_for_user(export_id, user_id, org_id)

    if not export_record:
        logger.warning(f"Export not found or access denied: export_id={export_id}, user_id={user_id}")
        raise HTTPException(
            status_code=404,
            detail="Export not found",
        )

    # Check if export is completed
    if export_record.status != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Export is not ready for download. Status: {export_record.status}",
        )

    try:
        # Generate presigned URL
        download_url = generate_download_url(
            key=export_record.s3_key,
            expires_seconds=expires_seconds,
        )

        logger.info(f"Generated download URL: export_id={export_id}, expires_in={expires_seconds}s")

        return S3ExportDownloadResponse(
            download_url=download_url,
            expires_in_seconds=expires_seconds,
        )

    except NoCredentialsError:
        logger.error("Failed to generate download URL: AWS credentials not configured")
        raise HTTPException(
            status_code=500,
            detail="S3 storage not configured. Contact administrator.",
        )
    except ClientError as e:
        logger.error(f"Failed to generate download URL: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to generate download URL. Please try again.",
        )


@router.get("/s3/list", response_model=S3ExportListResponse)
async def list_s3_exports(
    status: Optional[str] = Query(None, description="Filter by status (pending, completed, failed)"),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of exports to return"),
    ctx: AuthContext = Depends(get_current_context),
):
    """
    List the authenticated user's S3 exports.

    Returns exports for the current user within their organization.
    """
    user_id = ctx["user_id"]
    org_id = ctx["org_id"]

    exports = list_user_exports(user_id, org_id, status=status, limit=limit)

    return S3ExportListResponse(
        exports=[e.to_dict() for e in exports],
        total=len(exports),
    )
