# app/stores.py (additions)

from __future__ import annotations

import os
import sqlite3
from typing import Dict, Optional

# Put the DB at the project root (same level as /app)
_DB_PATH = os.path.join(os.getcwd(), "reconai.db")


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """
    Create tables if they don't exist.
    Call this once at startup (main.py).
    """
    with _db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS merchant_feedback (
                merchant_key TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.commit()


def _merchant_key(merchant: str) -> str:
    return (merchant or "").strip().lower()


def set_merchant_feedback(merchant: str, label: str) -> None:
    """
    label must be one of: business, personal, uncertain
    """
    key = _merchant_key(merchant)
    if not key:
        raise ValueError("merchant cannot be empty")

    if label not in ("business", "personal", "uncertain"):
        raise ValueError("label must be one of: business, personal, uncertain")

    with _db() as conn:
        conn.execute(
            """
            INSERT INTO merchant_feedback (merchant_key, label, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(merchant_key) DO UPDATE SET
                label=excluded.label,
                updated_at=datetime('now')
            """,
            (key, label),
        )
        conn.commit()


def get_merchant_feedback(merchant: str) -> Optional[str]:
    key = _merchant_key(merchant)
    if not key:
        return None

    with _db() as conn:
        row = conn.execute(
            "SELECT label FROM merchant_feedback WHERE merchant_key=?",
            (key,),
        ).fetchone()
        return row["label"] if row else None


def get_all_merchant_feedback() -> Dict[str, str]:
    """
    Returns dict: merchant_key -> label
    """
    with _db() as conn:
        rows = conn.execute(
            "SELECT merchant_key, label FROM merchant_feedback"
        ).fetchall()
        return {r["merchant_key"]: r["label"] for r in rows}

# ---------------------------
# Merchant feedback overrides
# ---------------------------

import sqlite3
from typing import Dict, Optional

from app.db import DB_PATH


def _norm_key(value: str) -> str:
    """
    Normalize merchant/description text into a consistent lookup key.
    """
    return (value or "").strip().lower()


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
