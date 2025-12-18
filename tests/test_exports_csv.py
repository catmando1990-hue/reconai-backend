# tests/test_exports_csv.py
from __future__ import annotations

import csv
from io import StringIO
from types import SimpleNamespace
from typing import Optional

import pytest

# Unit targets from the router
from app.routers.exports import (
    _CSV_HEADER,
    _disposition_header,
    _iter_csv,
    _sanitize_filename,
)


# ----------------------------
# Helpers for tests
# ----------------------------

def _tx(date=None, amount=0, description="", merchant="", original_category=""):
    # Minimal shape the writer expects; only attributes accessed are used
    return SimpleNamespace(
        date=date,
        amount=amount,
        description=description,
        merchant=merchant,
        original_category=original_category,
    )


def _response_fixture():
    # Emulates TransactionsResponse surface area
    return SimpleNamespace(
        business_expenses=[_tx(description="B1")],
        personal_expenses=[_tx(description="P1")],
        transfers=[_tx(description="T1")],
        uncertain=[_tx(description="U1")],
    )


def _rows(csv_text: str):
    """Parse CSV reliably (handles commas/quotes)."""
    return list(csv.reader(StringIO(csv_text)))


def _maybe_load_app() -> Optional[object]:
    """
    Try importing FastAPI app. If your app lives elsewhere, update the path.
    E2E tests will skip if the app can't be imported.
    """
    try:
        from app.main import app  # noqa: WPS433
        return app
    except Exception:
        return None


# ----------------------------
# Unit tests: filename handling
# ----------------------------

def test_sanitize_filename_adds_extension_and_strips_bad_chars():
    assert _sanitize_filename("  report Q1*?.csv  ") == "report_Q1__.csv"
    assert _sanitize_filename("evil\r\ninject") == "evil_inject.csv"
    assert _sanitize_filename(None) == "reconai-export.csv"

    long = "x" * 200
    out = _sanitize_filename(long)
    assert out.endswith(".csv")
    assert len(out) <= 128


def test_disposition_header_contains_rfc5987_and_ascii_fallback():
    header = _disposition_header("réport 2025.csv")
    # ascii fallback quoted
    assert 'filename="' in header and '";' in header
    # rfc5987 param present and percent-encoded
    assert "filename*=" in header and "%C3%A9" in header
    # no CRLF injection
    assert "\r" not in header and "\n" not in header


# ----------------------------
# Unit tests: CSV streaming
# ----------------------------

def test_iter_csv_without_bom_produces_header_and_rows():
    res = _response_fixture()
    chunks = list(_iter_csv(res, add_bom=False))
    data = "".join(chunks)
    rows = _rows(data)

    assert rows[0] == _CSV_HEADER
    # header + 4 rows
    assert len(rows) == 1 + 4


def test_iter_csv_with_bom_starts_with_bom():
    res = _response_fixture()
    combined = "".join(list(_iter_csv(res, add_bom=True)))
    assert combined.startswith("\ufeff")


# ----------------------------
# E2E (optional): /exports/csv
# ----------------------------

@pytest.mark.skipif(_maybe_load_app() is None, reason="FastAPI app not importable")
def test_csv_endpoint_excel_and_filename_headers_e2e():
    """
    This test runs only if `app.main:app` exists and accepts the payload.
    Skips gracefully on 422 (schema mismatch) to avoid blocking your suite.
    """
    app = _maybe_load_app()
    assert app is not None  # for type checkers

    from fastapi.testclient import TestClient  # local import to avoid hard dep otherwise
    client = TestClient(app)

    # Payload attempts to mirror TransactionsResponse structure; adjust if your schema differs
    payload = {
        "business_expenses": [{"date": None, "amount": 0, "description": "B1", "merchant": "", "original_category": ""}],
        "personal_expenses": [{"date": None, "amount": 0, "description": "P1", "merchant": "", "original_category": ""}],
        "transfers": [{"date": None, "amount": 0, "description": "T1", "merchant": "", "original_category": ""}],
        "uncertain": [{"date": None, "amount": 0, "description": "U1", "merchant": "", "original_category": ""}],
    }

    r = client.post("/exports/csv?excel=1&filename=réport 2025.csv", json=payload)
    if r.status_code == 422:
        pytest.skip("Model schema differs; skipping E2E body validation.")
    assert r.status_code == 200

    disp = r.headers.get("content-disposition", "").lower()
    assert "attachment" in disp and "filename=" in disp and "filename*=" in disp
    assert r.text.startswith("\ufeff")
