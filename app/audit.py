"""ReconAI audit compatibility module.

Why this file exists:
- Some routers import `record_audit_event` from `app.audit`.
- If the canonical audit implementation lives elsewhere (or is refactored),
  this module prevents import-time crashes on deploy.

Preferred shape:
- Re-export a real implementation if present.
- Otherwise, provide a best-effort fallback that never blocks requests.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger("reconai.audit")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_json(obj: Any) -> str:
    try:
        return json.dumps(obj, default=str, ensure_ascii=False)
    except Exception:
        return json.dumps({"unserializable": True, "type": str(type(obj))})


# ---- Preferred: re-export a canonical implementation if you have one ----
# If you already have a real audit system, uncomment and update the import below:
#
# from app.governance.audit import record_audit_event  # noqa: F401
#
# or:
# from app.utils.audit import record_audit_event  # noqa: F401
#
# Keep the fallback below only if you truly have no other implementation.


async def record_audit_event(
    *,
    actor: Optional[Dict[str, Any]] = None,
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    status: str = "ok",
    metadata: Optional[Dict[str, Any]] = None,
    request_id: Optional[str] = None,
) -> None:
    """Best-effort audit event recorder.

    - Never raises (fail-open) to avoid taking down the API.
    - Emits a structured log line that Render will retain.
    - If you later wire a DB/immutable audit seal, replace this with the canonical implementation.
    """
    try:
        payload = {
            "ts": _utc_iso(),
            "request_id": request_id,
            "actor": actor,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "status": status,
            "metadata": metadata or {},
        }
        logger.info("AUDIT %s", _safe_json(payload))
    except Exception:
        # Absolutely never block a request because auditing failed.
        logger.exception("AUDIT_WRITE_FAILED")
        return
