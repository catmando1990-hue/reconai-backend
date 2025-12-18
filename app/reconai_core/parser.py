# app/reconai_core/parser.py
from typing import List, Optional
import datetime
from datetime import datetime as dt

from ..models import Transaction


def parse_raw_lines(raw_text: str) -> List[Transaction]:
    """
    Very simple parser for CSV / line-based text.
    Expected formats per line (comma-separated):

    date, amount, description, merchant, category?

    Examples:
        2025-01-01, -20.50, Walmart groceries, Walmart, groceries
        2025-01-02, 1500, Invoice payment from client, ACME Corp, income
    """
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    txs: List[Transaction] = []

    for line in lines:
        # Skip comments
        if line.startswith("#"):
            continue

        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            # Not enough info, skip the line
            continue

        # date (optional)
        tx_date: Optional[datetime.date] = None
        try:
            tx_date = dt.fromisoformat(parts[0]).date()
            amount_str = parts[1]
            rest = parts[2:]
        except Exception:
            # No valid date at the start; treat first field as amount
            amount_str = parts[0]
            rest = parts[1:]

        try:
            amount_val = float(amount_str)
        except ValueError:
            # If we can't parse amount, skip the line
            continue

        description = rest[0] if rest else ""
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
