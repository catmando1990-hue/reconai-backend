# app/reconai_core/parser.py
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional

from app.models import Transaction

# Generic helpers used as fallbacks when bank-specific parsing doesn't work.

@dataclass
class TextParseResult:
    transactions: List[Transaction]
    notes: List[str]


_MMDD_RE = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-]?(\d{2,4})?\b")
_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)
_MONTH_HEADER_RE = re.compile(rf"\b({'|'.join(_MONTHS)})\s+(\d{{1,2}}),\s*(\d{{4}})\b")

_AMOUNT_RE = re.compile(r"[-+]?\$?\d{1,3}(?:,\d{3})*(?:\.\d{2})|[-+]?\$?\d+(?:\.\d{2})")


def _clean(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _parse_date_mmdd(line: str, default_year: Optional[int] = None) -> Optional[date]:
    m = _MMDD_RE.search(line or "")
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


def _parse_date_month_header(line: str) -> Optional[date]:
    m = _MONTH_HEADER_RE.search(line or "")
    if not m:
        return None
    try:
        return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%B %d %Y").date()
    except Exception:
        return None


def parse_text_lines(text: str) -> TextParseResult:
    """
    Generic text parser:
    - Supports mm/dd/yy style dates, OR 'December 17, 2025' headers.
    - Extracts any line containing (date + amount) or uses date headers to tag subsequent amount lines.
    """
    lines = [_clean(l) for l in (text or "").splitlines() if _clean(l)]
    notes: List[str] = []
    txs: List[Transaction] = []

    current_date: Optional[date] = None
    for idx, ln in enumerate(lines):
        # update date header context
        dh = _parse_date_month_header(ln)
        if dh:
            current_date = dh
            continue
        md = _parse_date_mmdd(ln)
        if md:
            current_date = md  # sometimes transactions include mm/dd without year
            # keep scanning the same line for amount too

        amts = _AMOUNT_RE.findall(ln)
        if not amts:
            continue

        # Try to decide if this looks like a transaction line.
        # We require either:
        # - line has a date + an amount, or
        # - we have a current_date header and this line is mostly an amount (or amount + short text)
        has_date_inline = _MMDD_RE.search(ln) is not None
        if not has_date_inline and current_date is None:
            continue

        amt_raw = amts[-1]
        amt = float(amt_raw.replace(",", "").replace("$", "").replace(" ", ""))
        desc = ln

        # If the line is only an amount, look back for description
        if _clean(desc).replace("$", "").replace(",", "").replace("-", "").replace("+", "").replace(".", "").isdigit():
            # look back up to 3 lines for a description
            for back in range(1, 4):
                if idx - back < 0:
                    break
                cand = lines[idx - back]
                if cand and _AMOUNT_RE.fullmatch(cand) is None:
                    desc = cand
                    break

        txs.append(
            Transaction(
                date=current_date,
                amount=amt,
                description=desc,
                merchant=None,
                classification=None,
                reason=None,
            )
        )

    if not txs:
        notes.append("Generic text parser could not confidently extract transactions from this input.")
    else:
        notes.append(f"Generic text parser extracted {len(txs)} candidate transactions.")

    return TextParseResult(transactions=txs, notes=notes)
