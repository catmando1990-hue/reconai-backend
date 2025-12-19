from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
import re

# Optional deps
try:
    import pandas as pd  # type: ignore
except Exception:
    pd = None  # type: ignore

try:
    from pypdf import PdfReader  # type: ignore
except Exception:
    PdfReader = None  # type: ignore


@dataclass
class Tx:
    date: Optional[str]
    amount: float
    description: str
    merchant: Optional[str] = None
    reason: Optional[str] = None


_DATE_RE = re.compile(r"(?:\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b)")
_AMT_RE = re.compile(r"[-+]?\$?\d{1,3}(?:,\d{3})*(?:\.\d{2})|[-+]?\$?\d+(?:\.\d{2})")


def _ext(filename: str) -> str:
    return Path(filename).suffix.lower().strip()


def _norm_amount(s: str) -> Optional[float]:
    s = s.strip()
    if not s:
        return None
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg = True
        s = s[1:-1]
    s = s.replace("$", "").replace(",", "").strip()
    try:
        v = float(s)
        return -v if neg else v
    except ValueError:
        return None


def _df_to_txs(df) -> List[Tx]:
    cols = {c.lower().strip(): c for c in df.columns}

    def find(*names: str) -> Optional[str]:
        for n in names:
            if n in cols:
                return cols[n]
        return None

    date_col = find("date", "posting date", "posted date", "transaction date")
    desc_col = find("description", "details", "memo", "transaction", "name", "merchant")
    amt_col = find("amount", "amt", "debit", "credit")

    if not desc_col or not amt_col:
        # fallback guess
        text_cols = [c for c in df.columns if df[c].dtype == object]
        num_cols = [c for c in df.columns if str(df[c].dtype).startswith(("int", "float"))]
        desc_col = desc_col or (text_cols[0] if text_cols else None)
        amt_col = amt_col or (num_cols[0] if num_cols else None)

    if not desc_col or not amt_col:
        raise ValueError("Could not infer description/amount columns")

    txs: List[Tx] = []
    for _, row in df.iterrows():
        desc = str(row.get(desc_col, "")).strip()
        if not desc:
            continue

        raw_amt = row.get(amt_col, "")
        try:
            amt = float(raw_amt)
        except Exception:
            amt = _norm_amount(str(raw_amt))
        if amt is None:
            continue

        date = str(row.get(date_col, "")).strip() if date_col else None
        txs.append(Tx(date=date or None, amount=float(amt), description=desc))

    return txs


def parse_csv(path: Path) -> List[Tx]:
    if pd is None:
        raise RuntimeError("Missing dependency: pandas (CSV/XLSX parsing)")
    df = pd.read_csv(path)
    return _df_to_txs(df)


def parse_excel(path: Path) -> List[Tx]:
    if pd is None:
        raise RuntimeError("Missing dependency: pandas + openpyxl (XLSX parsing)")
    df = pd.read_excel(path)
    return _df_to_txs(df)


def parse_pdf_text(path: Path, max_pages: int = 8) -> str:
    if PdfReader is None:
        raise RuntimeError("Missing dependency: pypdf (PDF parsing)")
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

        amt = _norm_amount(amts[-1])
        if amt is None:
            continue

        date = mdate.group(1)
        desc = ln.replace(date, "").replace(amts[-1], "").strip()
        desc = re.sub(r"\s{2,}", " ", desc).strip() or "PDF transaction"

        txs.append(Tx(date=date, amount=amt, description=desc, reason="pdf_heuristic"))

    return txs


def analyze_upload(
    path: Path,
    filename: str,
    content_type: Optional[str],
    classify_fn,
) -> Dict[str, Any]:
    """
    classify_fn(records: List[dict]) -> ReconAIResponse-like dict
    records: {"date": str|None, "amount": float, "description": str, "merchant": str|None}
    """
    ext = _ext(filename)
    ct = (content_type or "").lower()

    notes: List[str] = []

    if ext == ".csv" or ct.endswith("csv"):
        txs = parse_csv(path)
        notes.append("Parsed CSV upload.")
    elif ext in (".xlsx", ".xls"):
        txs = parse_excel(path)
        notes.append("Parsed Excel upload.")
    elif ext == ".pdf" or ct.endswith("pdf"):
        txs = parse_pdf_transactions(path)
        notes += [
            "Parsed PDF upload (best-effort).",
            "PDF extraction is heuristic; improve parser rules as you collect samples.",
        ]
    else:
        raise ValueError(f"Unsupported file type for analysis: {ext or ct or 'unknown'}")

    records = [
        {"date": t.date, "amount": t.amount, "description": t.description, "merchant": t.merchant}
        for t in txs
    ]

    result = classify_fn(records)

    # Append notes safely
    try:
        result.setdefault("summary_notes", [])
        if isinstance(result["summary_notes"], list):
            result["summary_notes"].extend(notes)
    except Exception:
        pass

    result.setdefault("parsing", {})
    try:
        result["parsing"].update(
            {
                "filename": filename,
                "content_type": content_type,
                "ext": ext,
                "parsed_records": len(records),
            }
        )
    except Exception:
        pass

    return result
