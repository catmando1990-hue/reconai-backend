# audit_api.py
# BUILD 5 — Read-Only Audit Log + Compliance Surface
# Read-only only. No new writes. Preserves auth isolation.

from typing import Optional
from fastapi import APIRouter, Depends, Query

from app.auth_context import get_current_context, AuthContext
from app.services.audit_service import get_audit_entries, get_audit_count


router = APIRouter(prefix="/api")


@router.get("/audit")
async def get_audit_log(
    entity: Optional[str] = Query(None, description="Filter by entity type"),
    action: Optional[str] = Query(None, description="Filter by action type"),
    limit: int = Query(100, le=100, description="Max entries to return (max 100)"),
    ctx: AuthContext = Depends(get_current_context),
):
    """
    GET /api/audit - Read-only audit log access

    Supports filters:
    - entity: Filter by entity type (e.g., "transaction", "plaid_item")
    - action: Filter by action type (e.g., "transaction_override", "plaid_sync_failed")

    Returns max 100 entries per request.
    """
    entries = get_audit_entries(entity=entity, action=action, limit=limit)

    return {
        "ok": True,
        "entries": entries,
        "total": get_audit_count(),
        "filtered_count": len(entries),
    }


@router.get("/audit/summary")
async def get_audit_summary(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    GET /api/audit/summary - Audit log summary for compliance

    Returns counts by entity and action types.
    """
    entries = get_audit_entries(limit=1000)

    # Count by entity
    entities: dict[str, int] = {}
    actions: dict[str, int] = {}

    for entry in entries:
        entity = entry.get("entity", "unknown")
        action = entry.get("action", "unknown")

        entities[entity] = entities.get(entity, 0) + 1
        actions[action] = actions.get(action, 0) + 1

    return {
        "ok": True,
        "total": get_audit_count(),
        "by_entity": entities,
        "by_action": actions,
    }
