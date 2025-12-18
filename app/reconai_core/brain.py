# app/reconai_core/brain.py

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict

from fastapi import HTTPException

from app.models import Transaction, TransactionsRequest, TransactionsResponse
from app import stores


@dataclass
class _Buckets:
    business: List[Transaction]
    personal: List[Transaction]
    transfers: List[Transaction]
    uncertain: List[Transaction]


class ReconAIBrain:
    """
    ReconAI classification + summary engine.

    - Accepts TransactionsRequest (structured/csv/text)
    - Normalizes into List[Transaction]
    - Classifies each tx: business / personal / transfer / uncertain
    - Applies merchant feedback overrides (from SQLite via app.stores)
    - Attaches classification + reason onto each Transaction (Option 2)
    """

    schema_version = "1.2.0"  # bumped due to per-tx explainability fields

    # -----------------------------
    # Public API
    # -----------------------------
    def analyze_transactions(self, payload: TransactionsRequest) -> TransactionsResponse:
        txs = self._normalize_input(payload)
        if not txs:
            raise HTTPException(status_code=400, detail="No valid transactions were found in the input.")

        buckets = _Buckets(business=[], personal=[], transfers=[], uncertain=[])
        total_outflow = 0.0
        total_inflow = 0.0

        # Pull all merchant feedback once (fast)
        merchant_feedback: Dict[str, str] = stores.get_all_merchant_feedback()  # dict: merchant_key -> label

        notes: List[str] = []
        explain_samples: List[str] = []

        for tx in txs:
            if tx.amount < 0:
                total_outflow += tx.amount
            else:
                total_inflow += tx.amount

            label, reason = self._classify_with_reason(tx, merchant_feedback)

            # Attach fields safely (pydantic v1 vs v2)
            if hasattr(tx, "model_copy"):
                tx = tx.model_copy(update={"classification": label, "reason": reason})
            else:
                tx = tx.copy(update={"classification": label, "reason": reason})

            # Bucket
            if label == "business":
                buckets.business.append(tx)
            elif label == "personal":
                buckets.personal.append(tx)
            elif label == "transfer":
                buckets.transfers.append(tx)
            else:
                buckets.uncertain.append(tx)

            # Keep a few explanation examples (so notes don't get huge)
            if len(explain_samples) < 12:
                who = (tx.merchant or tx.description or "tx").strip()
                explain_samples.append(f"{who}: {reason}")

        net = total_inflow + total_outflow  # outflow is negative

        notes.append(
            f"Classified {len(buckets.business)} transactions as likely business, "
            f"{len(buckets.personal)} as personal, {len(buckets.transfers)} as transfers, "
            f"and {len(buckets.uncertain)} as uncertain."
        )

        if payload.goal == "tax_prep":
            notes.append(
                "Goal is tax_prep: treat 'business_expenses' as candidate deductions; "
                "you should still review them manually or with a tax professional."
            )
        elif payload.goal == "business_expenses":
            notes.append("Goal is business_expenses: focus on separating business from personal spend.")
        else:
            notes.append("Goal is general_analysis: showing overall inflow/outflow and basic categories.")

        if explain_samples:
            notes.append("Explainability samples (first 12):")
            notes.extend(explain_samples)

        return TransactionsResponse(
            schema_version=self.schema_version,
            total_transactions=len(txs),
            total_outflow=round(total_outflow, 2),
            total_inflow=round(total_inflow, 2),
            net=round(net, 2),
            business_expenses=buckets.business,
            personal_expenses=buckets.personal,
            transfers=buckets.transfers,
            uncertain=buckets.uncertain,
            summary_notes=notes,
        )

    # -----------------------------
    # Input normalization
    # -----------------------------
    def _normalize_input(self, payload: TransactionsRequest) -> List[Transaction]:
        if payload.source_type == "structured":
            if not payload.transactions:
                raise HTTPException(
                    status_code=400,
                    detail="source_type='structured' requires 'transactions' to be provided.",
                )
            return payload.transactions

        # csv / text -> raw_text required
        if not payload.raw_text:
            raise HTTPException(
                status_code=400,
                detail=f"source_type='{payload.source_type}' requires 'raw_text' to be provided.",
            )

        return self._parse_raw_lines(payload.raw_text)

    def _parse_raw_lines(self, raw_text: str) -> List[Transaction]:
        """
        Very simple parser for CSV / line-based text.
        Expected formats per line (comma-separated):

            date, amount, description, merchant, category?

        Examples:
            2025-01-01, -20.50, Walmart groceries, Walmart, groceries
            1500, Invoice payment from client, ACME Corp, income
        """
        lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
        txs: List[Transaction] = []

        for line in lines:
            if line.startswith("#"):
                continue

            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 2:
                continue

            tx_date: Optional[dt.date] = None

            # Try: first token is date
            amount_str = None
            rest: List[str] = []
            try:
                tx_date = dt.date.fromisoformat(parts[0])
                amount_str = parts[1]
                rest = parts[2:]
            except Exception:
                amount_str = parts[0]
                rest = parts[1:]

            try:
                amount_val = float(amount_str)
            except Exception:
                continue

            description = rest[0] if len(rest) > 0 else ""
            merchant = rest[1] if len(rest) > 1 else None
            original_category = rest[2] if len(rest) > 2 else None

            txs.append(
                Transaction(
                    date=tx_date,
                    amount=amount_val,
                    description=description,
                    merchant=merchant,
                    original_category=original_category,
                )
            )

        return txs

    # -----------------------------
    # Classification + explainability
    # -----------------------------
    def _classify_with_reason(self, tx: Transaction, merchant_feedback: Dict[str, str]) -> Tuple[str, str]:
        """
        Returns: (label, reason)
        label: business | personal | transfer | uncertain

        Precedence:
          1) Merchant feedback override
          2) Transfer heuristics
          3) Keyword rules
          4) Income heuristic
          5) uncertain
        """

        merchant_key = (tx.merchant or "").strip().lower()
        if merchant_key:
            override = merchant_feedback.get(merchant_key)
            if override in ("business", "personal", "transfer", "uncertain"):
                return override, f"merchant_override:{merchant_key}->{override}"

        text = f"{tx.description or ''} {tx.merchant or ''} {tx.original_category or ''}".lower()

        # Transfer heuristics (run early)
        transfer_keywords = [
            "credit card payment", "cc payment", "autopay",
            "transfer", "ach", "zelle", "venmo", "cash app",
            "internal transfer", "from savings", "to savings",
            "payment to", "payment from",
        ]
        if any(kw in text for kw in transfer_keywords):
            return "transfer", "keyword:transfer->transfer"

        business_keywords = [
            "llc", "inc", "corp",
            "stripe", "square", "quickbooks", "shopify",
            "fuel", "gas", "shell", "chevron", "exxon",
            "hotel", "motel", "airbnb", "marriott", "hilton", "hyatt",
            "uber", "lyft", "airport", "airlines",
            "office", "software", "subscription", "zoom", "slack",
            "ads", "google ads", "facebook ads",
            "equipment", "tools", "hardware",
            "security", "training", "consulting", "invoice", "client",
        ]

        personal_keywords = [
            "netflix", "hulu", "spotify", "disney", "prime video",
            "walmart", "target",
            "mcdonald", "starbucks", "chipotle",
            "xbox", "playstation", "gamestop",
            "movie", "theater",
            "grocery", "groceries",
        ]

        for kw in business_keywords:
            if kw in text:
                return "business", f"keyword:{kw}->business"

        for kw in personal_keywords:
            if kw in text:
                return "personal", f"keyword:{kw}->personal"

        # Income heuristic (only on inflows)
        if tx.amount > 0:
            income_keywords = ["invoice", "salary", "payroll", "deposit"]
            for kw in income_keywords:
                if kw in text:
                    return "business", f"income_heuristic:{kw}->business"

        return "uncertain", "default->uncertain"
