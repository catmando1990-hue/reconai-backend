# app/reconai_core/bank_pdf.py
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional, Tuple

# pypdf is optional at import time (Render will have it if installed)
try:
    from pypdf import PdfReader  # type: ignore
except Exception:  # pragma: no cover
    PdfReader = None  # type: ignore

from app.models import Transaction


@dataclass
class BankParseResult:
    bank_name: Optional[str]
    transactions: List[Transaction]
    notes: List[str]


# ----------------------------
# PDF text extraction
# ----------------------------

def extract_text_from_pdf(path: str, max_pages: int = 12) -> Tuple[str, List[str]]:
    """Extract text from a PDF. Returns (text, notes)."""
    notes: List[str] = []
    if PdfReader is None:
        return "", ["pypdf is not installed on the backend."]

    try:
        reader = PdfReader(path)
    except Exception as e:
        return "", [f"Failed to open PDF: {e}"]

    parts: List[str] = []
    pages = reader.pages[: max_pages or 12]
    for i, page in enumerate(pages):
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            notes.append(f"Page {i+1}: text extraction failed")
            continue

    text = "\n".join(parts).strip()
    if not text:
        notes.append("PDF text extraction returned empty text (likely scanned / image-based PDF).")
    return text, notes


# ----------------------------
# Bank detection
# ----------------------------

_BANK_HINTS: list[tuple[str, list[str]]] = [
    ("Navy Federal Credit Union", ["NAVY FEDERAL", "NFCU", "navyfederal.org", "digitalomni.navyfederal"]),
    ("Chase", ["JPMORGAN CHASE", "CHASE.COM", "Chase", "jpmorgan"]),
    ("Bank of America", ["BANK OF AMERICA", "BofA", "bankofamerica.com"]),
    ("Wells Fargo", ["WELLS FARGO", "wellsfargo.com"]),
    ("USAA", ["USAA", "usaa.com"]),
    ("Capital One", ["CAPITAL ONE", "capitalone.com"]),
]


def detect_bank(text: str) -> Optional[str]:
    t = (text or "").upper()
    for name, hints in _BANK_HINTS:
        if any(h.upper() in t for h in hints):
            return name
    return None


# ----------------------------
# Parsing helpers
# ----------------------------

_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)

DATE_HEADER_RE = re.compile(
    rf"\b({'|'.join(_MONTHS)})\s+(\d{{1,2}}),\s*(\d{{4}})\b"
)

MMDDYY_RE = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-]?(\d{2,4})?\b")

AMOUNT_RE = re.compile(
    r"(?<!\d)(-?\$?\d{1,3}(?:,\d{3})*(?:\.\d{2})|-?\$?\d+(?:\.\d{2}))"
)

TRAILING_BALANCE_RE = re.compile(r"^\$?\d{1,3}(?:,\d{3})*(?:\.\d{2})$")


def _parse_amount(raw: str) -> Optional[float]:
    s = (raw or "").strip()
    if not s:
        return None
    s = s.replace(",", "")
    # handle "- $54.27"
    s = s.replace("$", "").replace(" ", "")
    try:
        return float(s)
    except Exception:
        return None


def _parse_date_header(line: str) -> Optional[date]:
    m = DATE_HEADER_RE.search(line or "")
    if not m:
        return None
    month_name, day_s, year_s = m.group(1), m.group(2), m.group(3)
    try:
        dt = datetime.strptime(f"{month_name} {day_s} {year_s}", "%B %d %Y").date()
        return dt
    except Exception:
        return None


def _parse_mmddyy(line: str, default_year: Optional[int] = None) -> Optional[date]:
    m = MMDDYY_RE.search(line or "")
    if not m:
        return None
    mm, dd, yy = m.group(1), m.group(2), m.group(3)
    try:
        month = int(mm)
        day = int(dd)
        if yy:
            y = int(yy)
            if y < 100:
                y += 2000
        else:
            y = default_year or datetime.utcnow().year
        return date(y, month, day)
    except Exception:
        return None


def _clean_line(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s


# ----------------------------
# Navy Federal (online banking export-style PDF)
# ----------------------------

def _parse_navy_federal_digitalomni(text: str) -> BankParseResult:
    """
    Handles PDFs like the user's upload where:
      - There are date headers: 'December 17, 2025'
      - Transactions are shown as blocks:
          POS $334.18
          Pos Debit 8554 Publix
          POS
          - $54.27
          $345.50   (balance, optional)
    We try to reconstruct (date, description, amount).
    """
    lines = [_clean_line(l) for l in (text or "").splitlines() if _clean_line(l)]
    notes: List[str] = ["Detected Navy Federal (digital banking export)."]
    txs: List[Transaction] = []

    current_date: Optional[date] = None

    i = 0
    while i < len(lines):
        ln = lines[i]

        # Date header like "December 17, 2025"
        dh = _parse_date_header(ln)
        if dh:
            current_date = dh
            i += 1
            continue

        # Some pages include mm/dd/yy timestamps; capture year if needed
        mmdd = _parse_mmddyy(ln)
        if mmdd:
            current_date = mmdd
            i += 1
            continue

        # Try to find an amount line (- $xx.xx or $xx.xx)
        # In Navy Fed export, amount may appear on its own line.
        amt_match = AMOUNT_RE.fullmatch(ln.replace(" ", ""))
        amt_val: Optional[float] = None
        if amt_match:
            amt_val = _parse_amount(amt_match.group(1))

        # If not fullmatch, sometimes line is like "- $54.27" with spaces; normalize
        if amt_val is None:
            m = AMOUNT_RE.search(ln)
            if m and _clean_line(ln).startswith(("-", "$")):
                amt_val = _parse_amount(m.group(1))

        if amt_val is not None:
            # Walk backwards a bit for a description line (skip category tokens like POS/Transfers)
            desc = None
            lookback = 1
            while lookback <= 4 and (i - lookback) >= 0:
                cand = lines[i - lookback]
                if cand.upper() in ("POS", "TRANSFERS", "OTHER EXPENSES", "RESTAURANTS/DINING", "TRAVEL", "PENDING", "ATTACH_MONEY"):
                    lookback += 1
                    continue
                # Ignore pure balances like $399.77
                if TRAILING_BALANCE_RE.match(cand.replace(" ", "").replace("$", "")) or cand.startswith("$"):
                    lookback += 1
                    continue
                desc = cand
                break

            # If still no desc, use a generic placeholder
            desc = desc or "Transaction"

            # Optional: derive a merchant field (first words before double spaces)
            merchant = desc
            merchant = re.sub(r"\b(Pos Debit|POS Debit)\b", "", merchant, flags=re.I).strip()

            txs.append(
                Transaction(
                    date=current_date,
                    amount=float(amt_val),
                    description=desc,
                    merchant=merchant or None,
                    classification=None,
                    reason=None,
                )
            )

        i += 1

    if not txs:
        notes.append("No transactions extracted from Navy Federal PDF text. This may be scanned or missing a recognizable layout.")
    else:
        notes.append(f"Extracted {len(txs)} candidate transactions from Navy Federal layout.")

    return BankParseResult(bank_name="Navy Federal Credit Union", transactions=txs, notes=notes)


# ----------------------------
# Public entrypoint
# ----------------------------

def parse_bank_statement_text(text: str) -> BankParseResult:
    bank = detect_bank(text or "")
    if bank == "Navy Federal Credit Union":
        return _parse_navy_federal_digitalomni(text)

    # Default: return empty but with detection note
    notes = []
    if bank:
        notes.append(f"Detected {bank}, but no bank-specific parser matched this statement layout yet.")
    else:
        notes.append("No bank detected from PDF text.")
    return BankParseResult(bank_name=bank, transactions=[], notes=notes)
