# audit_service.py
# BUILD 5 — Centralized Audit Log Service (Read-Only API)
# Provides unified audit access across all modules

from datetime import datetime
from typing import Optional

# Centralized audit store - all modules should use this
audit_store: list[dict] = []


def record_audit(
    actor: str,
    action: str,
    entity: str,
    entity_id: str,
    payload: Optional[dict] = None,
) -> dict:
    """Record an audit entry. Used by all write operations."""
    entry = {
        "actor": actor,
        "action": action,
        "entity": entity,
        "entity_id": entity_id,
        "payload": payload or {},
        "timestamp": datetime.utcnow().isoformat(),
    }
    audit_store.append(entry)
    return entry


def get_audit_entries(
    entity: Optional[str] = None,
    action: Optional[str] = None,
    limit: int = 100,
) -> list[dict]:
    """Get audit entries with optional filters. Read-only."""
    entries = audit_store.copy()

    if entity:
        entries = [e for e in entries if e.get("entity") == entity]

    if action:
        entries = [e for e in entries if e.get("action") == action]

    # Limit responses (max 100)
    return entries[-limit:] if len(entries) > limit else entries


def get_audit_count() -> int:
    """Get total count of audit entries."""
    return len(audit_store)
