from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List
import re

try:
    from pypdf import PdfReader  # type: ignore
except Exception:  # pragma: no cover
    PdfReader = None  # type: ignore

try:
    import pandas as pd  # type: ignore
except Exception:  # pragma: no cover
    pd = None  # type: ignore


@dataclass
class Tx:
    date: Optional[str]
    amount: float
    description: str


_DATE_RE = re.compile(r"(?:\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b)")
_AMT_RE = re.compile(r"[-+]?\$?\d{1,3}(?:,\d{3})*(?:\.\d{2})|[-+]?\$?\d+(?:\.\d{2})")


def parse_pdf_text(path: Path, max_pages: int = 8) -> str:
    if PdfReader is None:
        raise RuntimeError("pypdf not installed")
    reader = PdfReader(str(path))
    parts: List[str] = []
    for page in reader.pages[:max_pages]:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            continue
    return "\n".join(parts)


def parse_pdf_transactions(path: Path) -> List[Tx]:
    text = parse_pdf_text(path)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    txs: List[Tx] = []
    for ln in lines:
        mdate = _DATE_RE.search(ln)
        if not mdate:
            continue
        amts = _AMT_RE.findall(ln)
        if not amts:
            continue
        date = mdate.group(1)
        amt = amts[-1]
        desc = ln.replace(date, "").replace(amt, "").strip() or "PDF transaction"
        # amount parsing left to caller (CSV flow in files.py)
        txs.append(Tx(date=date, amount=0.0, description=desc))
    return txs


def read_csv_as_df(path: Path):
    if pd is None:
        raise RuntimeError("pandas not installed")
    return pd.read_csv(path)


def read_excel_as_df(path: Path):
    if pd is None:
        raise RuntimeError("pandas not installed")
    return pd.read_excel(path)

