# app/stores.py
"""
Merchant feedback overrides - single authoritative implementation.
P0 Security Fix: Deduplicated functions to ensure single implementation.
"""

from __future__ import annotations

import sqlite3
from typing import Dict, Optional

from app.db import DB_PATH


def _norm_key(value: str) -> str:
    """
    Normalize merchant/description text into a consistent lookup key.
    """
    return (value or "").strip().lower()


# Alias for backward compatibility
_merchant_key = _norm_key


def init_db() -> None:
    """
    Create tables if they don't exist.
    Call this once at startup (main.py).
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS merchant_feedback (
                merchant_key TEXT PRIMARY KEY,
                correct_label TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.commit()


def set_merchant_feedback(merchant: str, correct_label: str) -> None:
    """
    Persist a merchant-level classification override.

    correct_label must be one of:
      - business
      - personal
      - uncertain
    """
    key = _norm_key(merchant)
    if not key:
        raise ValueError("merchant cannot be empty")

    if correct_label not in ("business", "personal", "uncertain"):
        raise ValueError(
            "correct_label must be one of: business, personal, uncertain"
        )

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO merchant_feedback (merchant_key, correct_label, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(merchant_key) DO UPDATE SET
                correct_label = excluded.correct_label,
                updated_at = datetime('now')
            """,
            (key, correct_label),
        )
        conn.commit()


def get_merchant_feedback(merchant: str) -> Optional[str]:
    """
    Return the override label for a merchant, if one exists.
    """
    key = _norm_key(merchant)
    if not key:
        return None

    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT correct_label FROM merchant_feedback WHERE merchant_key = ?",
            (key,),
        ).fetchone()

    return row[0] if row else None


def get_all_merchant_feedback() -> Dict[str, str]:
    """
    Load all merchant overrides into memory.

    Returns:
        dict[str, str]: merchant_key -> correct_label
    """
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT merchant_key, correct_label FROM merchant_feedback"
        ).fetchall()

    return {merchant_key: correct_label for merchant_key, correct_label in rows}
