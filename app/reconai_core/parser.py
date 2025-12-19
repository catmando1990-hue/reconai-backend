# app/reconai_core/parser.py
from __future__ import annotations

import csv
import datetime as dt
import io
import re
from dataclasses import dataclass
from typing import List, Optional, Sequence

from app.models import Transaction


# -----------------------------
# Parsed wrapper
# -----------------------------

@dataclass
class ParsedInput:
    transactions: List[Transaction]
    notes: List[str]
    source_text: Optional[str] = None


def _parse_date(s: str) -> Optional[dt.date]:
    s = (s or "").strip()
    if not s:
        return None

    # Common formats: MM/DD/YYYY, MM/DD/YY, YYYY-MM-DD
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except Exception:
            continue
    return None


def _parse_amount(s: str) -> Optional[float]:
    if s is None:
        return None
    raw = str(s).strip()
    if not raw:
        return None

    # (123.45) -> -123.45
    neg = False
    if raw.startswith("(") and raw.endswith(")"):
        neg = True
        raw = raw[1:-1]

    raw = raw.replace("$", "").replace(",", "").strip()

    # some statements use trailing CR to indicate credit
    if raw.lower().endswith("cr"):
        raw = raw[:-2].strip()

    try:
        val = float(raw)
        return -val if neg else val
    except Exception:
        return None


def _merchant_guess(desc: str) -> str:
    # Basic merchant guess: first token chunk
    desc = (desc or "").strip()
    if not desc:
        return ""
    # Remove card numbers / ref
    desc = re.sub(r"\b\d{4,}\b", "", desc).strip()
    return desc.split("  ")[0].split("  ")[0].split(" ")[0:4] and " ".join(desc.split()[:3]) or desc


# -----------------------------
# Structured
# -----------------------------

def parse_structured_transactions(items: Sequence[Transaction]) -> ParsedInput:
    return ParsedInput(transactions=list(items), notes=["Parsed structured transactions."], source_text=None)


# -----------------------------
# CSV
# -----------------------------

def parse_csv_text(raw_csv: str) -> ParsedInput:
    raw_csv = raw_csv or ""
    f = io.StringIO(raw_csv)
    reader = csv.DictReader(f)

    txs: List[Transaction] = []
    notes: List[str] = ["Parsed CSV input."]

    if not reader.fieldnames:
        return ParsedInput([], ["CSV had no header/fields."], source_text=raw_csv)

    # Flexible column mapping
    def get(row, *keys):
        for k in keys:
            if k in row and row[k] is not None:
                return row[k]
        return None

    for row in reader:
        date_s = get(row, "date", "Date", "Posting Date", "Posted Date", "Trans Date", "Transaction Date")
        desc = get(row, "description", "Description", "Merchant", "Payee", "Name") or ""
        amt_s = get(row, "amount", "Amount", "Debit", "Credit", "Transaction Amount")

        # Handle split debit/credit columns
        debit = get(row, "Debit", "debit")
        credit = get(row, "Credit", "credit")
        amt = _parse_amount(amt_s) if amt_s is not None else None

        if amt is None:
            d = _parse_amount(debit)
            c = _parse_amount(credit)
            if d is not None and d != 0:
                amt = -abs(d)
            elif c is not None and c != 0:
                amt = abs(c)

        if amt is None:
            continue

        txs.append(
            Transaction(
                date=_parse_date(str(date_s)) if date_s else None,
                amount=float(amt),
                description=str(desc),
                merchant=_merchant_guess(str(desc)),
            )
        )

    if not txs:
        notes.append("No valid transactions were found in CSV.")

    return ParsedInput(txs, notes, source_text=raw_csv)


# -----------------------------
# Semi-structured text
# -----------------------------

_DATE_RE = re.compile(r"\b(\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)\b")
_AMT_RE = re.compile(r"[-+]?\$?\d{1,3}(?:,\d{3})*(?:\.\d{2})|[-+]?\$?\d+(?:\.\d{2})")


def parse_text_lines(raw_text: str) -> ParsedInput:
    raw_text = (raw_text or "").strip()
    if not raw_text:
        return ParsedInput([], ["Empty text input."], source_text="")

    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    txs: List[Transaction] = []
    notes: List[str] = ["Parsed semi-structured text input."]

    # Greedy line-based parsing
    for ln in lines:
        mdate = _DATE_RE.search(ln)
        if not mdate:
            continue
        amts = _AMT_RE.findall(ln)
        if not amts:
            continue

        date_s = mdate.group(1)
        amt_s = amts[-1]
        desc = ln.replace(date_s, "").replace(amt_s, "").strip()
        amt = _parse_amount(amt_s)
        if amt is None:
            continue

        txs.append(
            Transaction(
                date=_parse_date(date_s),
                amount=float(amt),
                description=desc or ln,
                merchant=_merchant_guess(desc or ln),
            )
        )

    if not txs:
        notes.append("No valid transactions were found in text.")

    return ParsedInput(txs, notes, source_text=raw_text)
