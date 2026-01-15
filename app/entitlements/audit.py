# app/entitlements/audit.py
# STEP 5 — Entitlement Audit Logging
# Logs all entitlement checks for compliance and analytics.

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from app.db import DB_PATH


def log_entitlement_check(
    user_id: str,
    org_id: Optional[str],
    feature: str,
    tier: str,
    allowed: bool,
    reason: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Log entitlement check to audit_logs table.
    Non-blocking — errors are silently ignored.
    """
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                INSERT INTO audit_logs (
                    id, timestamp, user_id, organization_id, action,
                    resource_type, resource_id, method, path, status_code,
                    ip_address, user_agent, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(uuid.uuid4()),
                datetime.utcnow().isoformat(),
                user_id,
                org_id,
                "ENTITLEMENT_CHECK",
                "entitlement",
                feature,
                "CHECK",
                f"/entitlements/{feature}",
                200 if allowed else 403,
                "api",
                "entitlements-guard",
                json.dumps({
                    "feature": feature,
                    "tier": tier,
                    "allowed": allowed,
                    "reason": reason,
                    **(metadata or {}),
                }),
            ))
            conn.commit()
    except Exception as e:
        # Non-blocking — log to stderr but don't fail the request
        print(f"Entitlement audit log error: {e}")
