# app/db.py
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

# ---------------------------------------
# Portable storage root (Render disk -> /var/data)
# ---------------------------------------
DATA_DIR = Path(os.getenv("DATA_DIR", "./data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# DB file path (overrideable)
DB_PATH = Path(os.getenv("DB_PATH", str(DATA_DIR / "reconai.db")))

def init_db() -> None:
    # ensure parent folder exists
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS user_tokens (
            user_id TEXT PRIMARY KEY,
            access_token TEXT NOT NULL,
            item_id TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS merchant_feedback (
            merchant_key TEXT PRIMARY KEY,
            correct_label TEXT NOT NULL,
            updated_at TEXT DEFAULT (datetime('now'))
        )
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS transaction_feedback (
            tx_id TEXT PRIMARY KEY,
            correct_label TEXT NOT NULL,
            updated_at TEXT DEFAULT (datetime('now'))
        )
        """)

        conn.commit()
