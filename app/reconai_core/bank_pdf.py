# app/reconai_core/bank_pdf.py
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from app.models import Transaction
from app.reconai_core.parser import _parse_amount, _parse_date, _merchant_guess


# -----------------------------
# Bank detection
# -----------------------------

BANK_MARKERS = {
    "Navy Federal": ["navy federal", "nfcu", "navy federal credit union"],
    "Chase": ["jpmorgan chase", "chase.com", "chase", "jp morgan"],
    "Bank of America": ["bank of america", "bofa", "ml.com", "bankofamerica"],
    "Wells Fargo": ["wells fargo", "wellsfargo"],
    "USAA": ["usaa"],
    "Capital One": ["capital one", "capitalone"],
}

def detect_institution(text: str) -> Optional[str]:
    t = (text or "").lower()
    for name, markers in BANK_MARKERS.items():
        if any(m in t for m in markers):
            return name
    return None


# -----------------------------
# Parsing result
# -----------------------------

@dataclass
class BankParseResult:
    institution: Optional[str]
    transactions: List[Transaction]
    notes: List[str]


# -----------------------------
# Text -> transactions (bank-aware)
# -----------------------------

# Common statement patterns
DATE_RE = re.compile(r"^(\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)\s+")
MONEY_RE = re.compile(r"[-+]?\$?\d{1,3}(?:,\d{3})*(?:\.\d{2})|[-+]?\$?\d+(?:\.\d{2})|\(\$?\d{1,3}(?:,\d{3})*(?:\.\d{2})\)")

# Some banks include two amount columns (debit/credit) and a balance.
# We'll parse the *last 1-2 money tokens* on the line and decide sign.
def _extract_amount_from_tokens(tokens: List[str], line: str) -> Optional[float]:
    # If line contains CR or CREDIT, treat as positive
    lc = line.lower()
    is_credit = (" cr" in lc) or ("credit" in lc) or ("deposit" in lc)
    is_debit_hint = ("debit" in lc) or ("withdrawal" in lc) or ("purchase" in lc)

    vals: List[float] = []
    for tok in tokens:
        v = _parse_amount(tok)
        if v is not None:
            vals.append(v)

    if not vals:
        return None

    # Usually: [amount, balance] or [debit, credit, balance]
    # We want the *transaction amount* not the balance: pick the second last if >=2 tokens.
    amt = vals[-2] if len(vals) >= 2 else vals[-1]

    # Apply sign hints if amount came out positive but should be debit
    if is_credit and amt < 0:
        amt = abs(amt)
    if (is_debit_hint or not is_credit) and amt > 0 and ("payment" not in lc and "deposit" not in lc):
        # heuristically treat as debit
        amt = -abs(amt)

    return float(amt)


def parse_bank_statement_text(text: str) -> BankParseResult:
    text = (text or "")
    institution = detect_institution(text)
    notes: List[str] = []
    if institution:
        notes.append(f"Detected institution: {institution}")
    else:
        notes.append("Institution not detected; using generic statement parsing.")

    # Normalize lines
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    # Some statements wrap descriptions to the next line. We'll merge continuation lines.
    merged: List[str] = []
    buf = ""

    for ln in lines:
        if DATE_RE.match(ln):
            if buf:
                merged.append(buf.strip())
            buf = ln
        else:
            # continuation line
            if buf:
                buf += " " + ln.strip()
            else:
                # ignore header noise
                continue
    if buf:
        merged.append(buf.strip())

    txs: List[Transaction] = []

    for ln in merged:
        m = DATE_RE.match(ln)
        if not m:
            continue
        date_s = m.group(1)
        rest = ln[m.end():].strip()

        money_tokens = MONEY_RE.findall(rest)
        if not money_tokens:
            continue

        amt = _extract_amount_from_tokens(money_tokens, rest)
        if amt is None:
            continue

        # Remove money tokens from description
        desc = rest
        for tok in money_tokens:
            desc = desc.replace(tok, " ")
        desc = re.sub(r"\s{2,}", " ", desc).strip()

        txs.append(
            Transaction(
                date=_parse_date(date_s),
                amount=float(amt),
                description=desc or rest,
                merchant=_merchant_guess(desc or rest),
            )
        )

    if not txs:
        notes.append("No transaction lines detected in extracted text. If this is scanned, enable OCR pipeline.")
    else:
        notes.append(f"Parsed {len(txs)} transactions from statement text.")

    return BankParseResult(institution=institution, transactions=txs, notes=notes)


# -----------------------------
# PDF -> text extraction (best-effort)
# -----------------------------

def extract_text_from_pdf(path: str, max_pages: int = 12) -> Tuple[str, List[str]]:
    notes: List[str] = []
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        return "", ["pypdf is not installed; cannot extract PDF text."]

    text_parts: List[str] = []
    try:
        reader = PdfReader(path)
        for page in reader.pages[:max_pages]:
            try:
                text_parts.append(page.extract_text() or "")
            except Exception:
                continue
    except Exception as e:
        return "", [f"Failed to read PDF: {e}"]

    text = "\n".join(text_parts).strip()
    if not text:
        notes.append("PDF text extraction returned empty text (likely scanned/image-based PDF).")
    else:
        notes.append("Extracted text from PDF using pypdf.")
    return text, notes
