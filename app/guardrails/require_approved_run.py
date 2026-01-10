# app/guardrails/require_approved_run.py
"""
Production startup guardrail: Blocks backend startup if latest deploy run is not approved.

Set REQUIRE_APPROVED_RUN=true in production to enforce.
"""

from __future__ import annotations

import os
import sqlite3

from app.db import DB_PATH


def enforce_approved_run() -> None:
    """
    Enforce that the latest deploy run is approved before allowing backend startup.

    This guardrail is only active when REQUIRE_APPROVED_RUN=true.
    In production, this ensures that no unapproved code reaches users.

    Raises:
        RuntimeError: If no approved run exists and guardrail is enabled.
    """
    if os.getenv("REQUIRE_APPROVED_RUN") != "true":
        return

    print(">> Checking deploy run approval status...")

    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT status FROM deploy_runs ORDER BY created_at DESC LIMIT 1"
            )
            row = cursor.fetchone()

            if not row:
                raise RuntimeError(
                    "DEPLOY BLOCKED: No deploy runs found. "
                    "Create and approve a run before starting production."
                )

            status = row["status"]
            if status != "approved":
                raise RuntimeError(
                    f"DEPLOY BLOCKED: Latest run status is '{status}', not 'approved'. "
                    "Approve the run via admin console before starting production."
                )

            print(f">> Deploy run approved. Status: {status}")

    except sqlite3.Error as e:
        raise RuntimeError(f"DEPLOY BLOCKED: Database error checking run status: {e}")
