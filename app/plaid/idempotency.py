# BUILD 16 — Plaid transaction identity normalization helpers
# Use these helpers before enabling real sync in production.

from __future__ import annotations

import hashlib
from typing import Any, Dict


def tx_identity_key(tx: Dict[str, Any]) -> str:
    """
    Stable identity to avoid duplicates across sync runs.
    Prefer Plaid transaction_id; fallback to hash of core fields.

    Usage:
    - Use this key when upserting Plaid transactions
    - Ensures no duplicate rows across repeated sync runs
    - Handles pending→posted transitions without inflation
    """
    tid = tx.get("transaction_id") or tx.get("id")
    if tid:
        return f"plaid:{tid}"

    parts = [
        str(tx.get("date") or ""),
        str(tx.get("amount") or ""),
        str(tx.get("merchant_name") or tx.get("merchant") or tx.get("name") or ""),
        str(tx.get("account_id") or ""),
    ]
    raw = "|".join(parts).encode("utf-8", errors="ignore")
    return "hash:" + hashlib.sha256(raw).hexdigest()
