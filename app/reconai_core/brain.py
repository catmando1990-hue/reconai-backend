# app/reconai_core/brain.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

from app.models import (
    Transaction,
    TransactionsRequest,
    TransactionsResponse,
)

from app.reconai_core.parser import (
    parse_structured_transactions,
    parse_csv_text,
    parse_text_lines,
    ParsedInput,
)
from app.reconai_core.bank_pdf import (
    detect_institution,
    BankParseResult,
)


# -----------------------------
# Lightweight heuristic classifier
# -----------------------------

@dataclass
class RuleHit:
    label: str
    reason: str


DEFAULT_KEYWORDS: Dict[str, str] = {
    # business-ish
    "aws": "business",
    "amazon web services": "business",
    "office": "business",
    "staples": "business",
    "quickbooks": "business",
    "intuit": "business",
    "adobe": "business",
    "microsoft": "business",
    "zoom": "business",
    "slack": "business",
    "google workspace": "business",
    "github": "business",
    "hosting": "business",
    "domain": "business",
    "insurance": "business",
    "fuel": "business",
    "shell": "business",
    "exxon": "business",
    "chevron": "business",
    "hotel": "business",
    "hilton": "business",
    "marriott": "business",

    # personal-ish
    "starbucks": "personal",
    "netflix": "personal",
    "spotify": "personal",
    "walmart": "personal",
    "target": "personal",
    "amazon.com": "personal",
}

TRANSFER_KEYWORDS = [
    "transfer",
    "ach transfer",
    "zelle",
    "venmo",
    "cash app",
    "paypal transfer",
    "p2p",
    "internal transfer",
    "online transfer",
]

LENDER_KEYWORDS = [
    "loan",
    "principal",
    "interest",
    "mortgage",
    "auto loan",
    "student loan",
    "payment received",
]


def _normalize(s: str) -> str:
    return (s or "").strip().lower()


def _classify_one(tx: Transaction) -> RuleHit:
    text = _normalize(f"{tx.merchant or ''} {tx.description or ''}")

    # Transfers
    for kw in TRANSFER_KEYWORDS:
        if kw in text:
            return RuleHit("transfer", f"keyword:{kw}->transfer")

    # Lender activity (usually personal unless user later maps to business)
    for kw in LENDER_KEYWORDS:
        if kw in text:
            # if amount is positive and says "payment received" treat as transfer-like inflow
            if "payment received" in text:
                return RuleHit("transfer", "keyword:payment received->transfer")
            return RuleHit("personal", f"keyword:{kw}->personal")

    # Keyword mapping
    for kw, lbl in DEFAULT_KEYWORDS.items():
        if kw in text:
            return RuleHit(lbl, f"keyword:{kw}->{lbl}")

    # Fallback: unknown
    return RuleHit("uncertain", "no_rule_match->uncertain")


def _bucketize(txs: List[Transaction]) -> Tuple[List[Transaction], List[Transaction], List[Transaction], List[Transaction]]:
    biz: List[Transaction] = []
    per: List[Transaction] = []
    trn: List[Transaction] = []
    unc: List[Transaction] = []

    for tx in txs:
        lbl = tx.classification or "uncertain"
        if lbl == "business":
            biz.append(tx)
        elif lbl == "personal":
            per.append(tx)
        elif lbl == "transfer":
            trn.append(tx)
        else:
            unc.append(tx)

    return biz, per, trn, unc


def _totals(txs: List[Transaction]) -> Tuple[int, float, float, float]:
    total = len(txs)
    outflow = 0.0
    inflow = 0.0
    for t in txs:
        if t.amount < 0:
            outflow += abs(float(t.amount))
        else:
            inflow += float(t.amount)
    net = inflow - outflow
    return total, outflow, inflow, net


# -----------------------------
# Brain
# -----------------------------

class ReconAIBrain:
    """Orchestrates parsing + classification + summary for Step 8."""

    def analyze_transactions(self, req: TransactionsRequest) -> TransactionsResponse:
        parsed: ParsedInput

        if req.source_type == "structured":
            parsed = parse_structured_transactions(req.transactions or [])
        elif req.source_type == "csv":
            parsed = parse_csv_text(req.raw_text or "")
        else:
            parsed = parse_text_lines(req.raw_text or "")

        # Classify
        out: List[Transaction] = []
        for tx in parsed.transactions:
            hit = _classify_one(tx)
            tx.classification = tx.classification or hit.label  # don't overwrite if already set
            tx.reason = tx.reason or hit.reason
            out.append(tx)

        total, outflow, inflow, net = _totals(out)
        biz, per, trn, unc = _bucketize(out)

        notes = []
        notes.extend(parsed.notes)

        # Add light explainability sample
        samples = [t for t in out[:12] if (t.reason or "").strip()]
        if samples:
            notes.append(f"Explainability samples (first {len(samples)}):")
            for t in samples:
                notes.append(f"- {t.merchant or t.description}: {t.reason}")

        return TransactionsResponse(
            total_transactions=total,
            total_outflow=float(outflow),
            total_inflow=float(inflow),
            net=float(net),
            business_expenses=biz,
            personal_expenses=per,
            transfers=trn,
            uncertain=unc,
            summary_notes=notes or ["OK"],
        )
