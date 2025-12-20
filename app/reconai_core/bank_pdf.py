# app/reconai_core/bank_pdf.py

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
from app.reconai_core.parser import _parse_amount, _parse_date, _merchant_guess


# -----------------------------
# Result container
# -----------------------------
@dataclass
class BankParseResult:
    bank_name: Optional[str]
    transactions: List[Transaction]
    notes: List[str]


# -----------------------------
# PDF text extraction (pypdf)
# -----------------------------
def extract_text_from_pdf(path: str, max_pages: int = 12) -> Tuple[str, List[str]]:
    """
    Extract text from a PDF using pypdf (best-effort).
    Returns (text, notes). If text is empty, this is likely a scanned/image PDF (needs OCR).
    """
    notes: List[str] = []

    if PdfReader is None:
        return "", ["pypdf is not installed on the backend."]

    try:
        reader = PdfReader(path)
    except Exception as e:
        return "", [f"Failed to open PDF: {e}"]

    parts: List[str] = []
    pages = reader.pages[: (max_pages or 12)]
    for i, page in enumerate(pages):
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            notes.append(f"Page {i+1}: text extraction failed")
            continue

    text = "\n".join(parts).strip()
    if not text:
        notes.append("PDF text extraction returned empty text (likely scanned / image-based PDF).")
    else:
        notes.append("Extracted text from PDF using pypdf.")
    return text, notes


# -----------------------------
# Bank detection
# -----------------------------
_BANK_HINTS: List[Tuple[str, List[str]]] = [
    ("Navy Federal Credit Union", ["NAVY FEDERAL", "NFCU", "NAVYFEDERAL.ORG", "DIGITALOMNI.NAVYFEDERAL"]),
    ("Chase", ["JPMORGAN CHASE", "CHASE.COM", "JPMORGAN", "CHASE"]),
    ("Bank of America", ["BANK OF AMERICA", "BANKOFAMERICA.COM", "BOFA", "ML.COM"]),
    ("Wells Fargo", ["WELLS FARGO", "WELLSFARGO.COM", "WELLSFARGO"]),
    ("USAA", ["USAA", "USAA.COM"]),
    ("Capital One", ["CAPITAL ONE", "CAPITALONE.COM", "CAPITALONE"]),
]


def detect_bank(text: str) -> Optional[str]:
    t = (text or "").upper()
    for name, hints in _BANK_HINTS:
        if any(h.upper() in t for h in hints):
            return name
    return None


# -----------------------------
# Navy Federal (digitalomni / online banking PDF layout)
# -----------------------------
_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)

DATE_HEADER_RE = re.compile(rf"\b({'|'.join(_MONTHS)})\s+(\d{{1,2}}),\s*(\d{{4}})\b")

# Amount lines are often like:
#   - $54.27
#   $334.18
#   ($54.27)
AMOUNT_LINE_RE = re.compile(
    r"^\s*(\(?\s*-?\s*\$?\s*\d{1,3}(?:,\d{3})*(?:\.\d{2})\s*\)?)\s*$"
)

# Noise / category lines that appear around entries
NFCU_SKIP = {
    "POS",
    "TRANSFERS",
    "OTHER EXPENSES",
    "RESTAURANTS/DINING",
    "TRAVEL",
    "PENDING",
    "ATTACH_MONEY",
}


def _clean_line(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _parse_date_header(line: str) -> Optional[date]:
    m = DATE_HEADER_RE.search(line or "")
    if not m:
        return None
    month_name, day_s, year_s = m.group(1), m.group(2), m.group(3)
    try:
        return datetime.strptime(f"{month_name} {day_s} {year_s}", "%B %d %Y").date()
    except Exception:
        return None


def _looks_like_balance(line: str) -> bool:
    # Balance-only lines frequently are just "$345.50" etc.
    s = _clean_line(line).replace("$", "").replace(",", "")
    return bool(re.fullmatch(r"\d+(?:\.\d{2})", s))


def _parse_navy_federal_digitalomni(text: str) -> BankParseResult:
    """
    Handles Navy Federal PDFs where transactions are displayed in blocks and the amount
    often appears on its own line.

    Strategy:
      - Track current_date from "Month DD, YYYY" headers.
      - When we see an amount-only line, walk backward for a usable description line.
      - Skip category/noise lines and balance-only lines.
    """
    lines = [_clean_line(l) for l in (text or "").splitlines()]
    lines = [l for l in lines if l]  # drop blanks

    notes: List[str] = ["Detected Navy Federal (digital banking export)."]
    txs: List[Transaction] = []

    current_date: Optional[date] = None

    for idx, ln in enumerate(lines):
        # Date header like "December 17, 2025"
        dh = _parse_date_header(ln)
        if dh:
            current_date = dh
            continue

        # Need a date context for transactions
        if current_date is None:
            continue

        # Amount-only line?
        m_amt = AMOUNT_LINE_RE.match(ln)
        if not m_amt:
            continue

        raw_amt = m_amt.group(1)
        amt_val = _parse_amount(raw_amt)
        if amt_val is None:
            continue

        # Find description above this line
        desc: Optional[str] = None
        for back in range(1, 7):
            j = idx - back
            if j < 0:
                break
            cand = lines[j]
            if not cand:
                continue
            if cand.upper() in NFCU_SKIP:
                continue
            if _looks_like_balance(cand):
                continue
            # skip repeating amount lines
            if AMOUNT_LINE_RE.match(cand):
                continue
            # stop if we hit another date header
            if _parse_date_header(cand):
                break
            desc = cand
            break

        if not desc:
            desc = "Transaction"

        merchant = _merchant_guess(desc) if desc else None

        txs.append(
            Transaction(
                date=current_date,
                amount=float(amt_val),
                description=desc,
                merchant=merchant,
                classification=None,
                reason=None,
            )
        )

    if not txs:
        notes.append("No transactions extracted from Navy Federal PDF text. If scanned, enable OCR pipeline.")
    else:
        notes.append(f"Extracted {len(txs)} candidate transactions from Navy Federal layout.")

    return BankParseResult(bank_name="Navy Federal Credit Union", transactions=txs, notes=notes)


# -----------------------------
# Public entrypoint: text -> transactions
# -----------------------------
def parse_bank_statement_text(text: str) -> BankParseResult:
    bank = detect_bank(text or "")
    if bank == "Navy Federal Credit Union":
        return _parse_navy_federal_digitalomni(text)

    notes: List[str] = []
    if bank:
        notes.append(f"Detected {bank}, but no bank-specific parser matched this statement layout yet.")
    else:
        notes.append("No bank detected from PDF text.")
    return BankParseResult(bank_name=bank, transactions=[], notes=notes)

# Alias for compatibility
detect_institution = detect_bank