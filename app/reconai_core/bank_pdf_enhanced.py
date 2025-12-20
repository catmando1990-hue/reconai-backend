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
from app.reconai_core.bank_intelligence import detect_bank as detect_bank_intelligent, BankProfile


# -----------------------------
# Result container
# -----------------------------
@dataclass
class BankParseResult:
    bank_name: Optional[str]
    bank_profile: Optional[BankProfile]  # NEW: Full bank profile info
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
# Bank detection (now uses bank_intelligence.py)
# -----------------------------
def detect_bank(text: str) -> Tuple[Optional[str], Optional[BankProfile]]:
    """
    Detect bank using the comprehensive bank intelligence system.
    Returns (bank_name, bank_profile)
    """
    profile = detect_bank_intelligent(text)
    if profile:
        return profile.name, profile
    return None, None


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


def _parse_navy_federal_digitalomni(text: str, profile: Optional[BankProfile]) -> BankParseResult:
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
    if profile:
        notes.append(f"Using bank profile: {profile.name} ({profile.institution_type})")
    
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

    return BankParseResult(
        bank_name="Navy Federal Credit Union",
        bank_profile=profile,
        transactions=txs,
        notes=notes
    )


# -----------------------------
# Import bank-specific parsers
# -----------------------------
try:
    from app.reconai_core.bank_parsers import get_parser_for_bank
    PARSERS_AVAILABLE = True
except ImportError:
    PARSERS_AVAILABLE = False
    get_parser_for_bank = None


# -----------------------------
# Generic parsers for other banks
# -----------------------------
def _parse_generic_bank_statement(text: str, profile: BankProfile) -> BankParseResult:
    """
    Use bank-specific parser if available, otherwise provide helpful message.
    """
    notes: List[str] = [
        f"Detected {profile.name} ({profile.institution_type})."
    ]
    
    # Try bank-specific parser if available
    if PARSERS_AVAILABLE and get_parser_for_bank:
        parser_func = get_parser_for_bank(profile.name)
        if parser_func:
            txs, parser_notes = parser_func(text, profile)
            notes.extend(parser_notes)
            return BankParseResult(
                bank_name=profile.name,
                bank_profile=profile,
                transactions=txs,
                notes=notes
            )
    
    # No specific parser available
    notes.append(f"Bank-specific parser for {profile.name} coming soon!")
    notes.append(f"Known columns: {', '.join(profile.known_columns)}")
    notes.append(f"For now, try uploading as CSV for best results.")
    
    return BankParseResult(
        bank_name=profile.name,
        bank_profile=profile,
        transactions=[],
        notes=notes
    )


# -----------------------------
# Public entrypoint: text -> transactions
# -----------------------------
def parse_bank_statement_text(text: str) -> BankParseResult:
    """
    Main entry point for parsing bank statement text.
    Uses bank intelligence system to detect and route to appropriate parser.
    """
    bank_name, profile = detect_bank(text or "")
    
    # Route to bank-specific parsers
    if bank_name == "Navy Federal Credit Union":
        return _parse_navy_federal_digitalomni(text, profile)
    
    # If we detected a bank but don't have a specific parser, use generic
    if profile:
        return _parse_generic_bank_statement(text, profile)
    
    # No bank detected
    notes: List[str] = [
        "No bank detected from PDF text.",
        "Upload may be a generic CSV, scanned document, or unsupported format."
    ]
    
    return BankParseResult(
        bank_name=None,
        bank_profile=None,
        transactions=[],
        notes=notes
    )


# Alias for compatibility
detect_institution = lambda text: detect_bank(text)[0]