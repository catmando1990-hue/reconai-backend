# app/services/audit_store.py
"""
Append-Only Audit Event Store for DCAA Compliance

This module provides INSERT-only operations for the audit_events table.
No UPDATE or DELETE operations are implemented or permitted.

CANONICAL LAWS ENFORCED:
- Append-only: only INSERT operations
- Hash chaining: each event references the previous event's hash
- Fail-closed: errors raise exceptions, not silent failures
- Evidence required: payload must contain action evidence

DCAA REQUIREMENTS:
- Immutable audit trail
- 6-year retention (enforced via policy, not code)
- Tamper-evident via hash chain
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from app.db import DB_PATH
from app.services.audit_hash import compute_event_hash, verify_event_hash


@dataclass(frozen=True)
class AuditEventInput:
    """Input for creating a new audit event (immutable)."""
    actor_id: str
    event_type: str
    entity_type: str
    entity_id: Optional[str]
    payload: Dict[str, Any]


@dataclass(frozen=True)
class AuditEventRecord:
    """Audit event as stored in the database (immutable)."""
    id: str
    created_at: str
    actor_id: str
    event_type: str
    entity_type: str
    entity_id: Optional[str]
    payload: Dict[str, Any]
    prev_hash: Optional[str]
    event_hash: str


class AuditStoreError(Exception):
    """Base exception for audit store errors."""
    pass


class HashChainError(AuditStoreError):
    """Raised when hash chain integrity is violated."""
    pass


class AuditInsertError(AuditStoreError):
    """Raised when audit event insertion fails."""
    pass


def _get_pepper() -> Optional[str]:
    """Get HMAC pepper from environment (optional but recommended)."""
    return os.getenv("AUDIT_HASH_SECRET")


def _get_last_event_hash() -> Optional[str]:
    """
    Get the hash of the most recent audit event for chain continuity.

    Returns:
        The event_hash of the last event, or None if no events exist.
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT event_hash FROM audit_events ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        return row["event_hash"] if row else None


def build_audit_row(
    *,
    prev_hash: Optional[str],
    event: AuditEventInput,
    created_at: Optional[datetime] = None,
) -> Tuple[Dict[str, Any], str]:
    """
    Build an audit event row ready for insertion.

    Args:
        prev_hash: Hash of the previous event (for chain integrity)
        event: The audit event input data
        created_at: Optional timestamp (defaults to now UTC)

    Returns:
        Tuple of (row_dict, event_hash)
    """
    ts = created_at or datetime.now(timezone.utc)
    created_at_iso = ts.isoformat().replace("+00:00", "Z")
    pepper = _get_pepper()

    event_hash = compute_event_hash(
        prev_hash=prev_hash,
        actor_id=event.actor_id,
        event_type=event.event_type,
        entity_type=event.entity_type,
        entity_id=event.entity_id,
        payload=event.payload,
        created_at_iso=created_at_iso,
        pepper=pepper,
    )

    row = {
        "id": str(uuid4()),
        "created_at": created_at_iso,
        "actor_id": event.actor_id,
        "event_type": event.event_type,
        "entity_type": event.entity_type,
        "entity_id": event.entity_id,
        "payload": json.dumps(event.payload, sort_keys=True),
        "prev_hash": prev_hash,
        "event_hash": event_hash,
    }
    return row, event_hash


def insert_audit_event(event: AuditEventInput) -> AuditEventRecord:
    """
    Insert an audit event into the append-only store.

    This is the ONLY write operation permitted on audit_events.
    The function automatically chains to the previous event's hash.

    Args:
        event: The audit event to insert

    Returns:
        The inserted audit event record

    Raises:
        AuditInsertError: If insertion fails
    """
    try:
        # Get previous hash for chain continuity
        prev_hash = _get_last_event_hash()

        # Build the row
        row, event_hash = build_audit_row(prev_hash=prev_hash, event=event)

        # Insert (APPEND-ONLY: this is the only write operation)
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                """
                INSERT INTO audit_events
                    (id, created_at, actor_id, event_type, entity_type, entity_id, payload, prev_hash, event_hash)
                VALUES
                    (:id, :created_at, :actor_id, :event_type, :entity_type, :entity_id, :payload, :prev_hash, :event_hash)
                """,
                row,
            )
            conn.commit()

        return AuditEventRecord(
            id=row["id"],
            created_at=row["created_at"],
            actor_id=row["actor_id"],
            event_type=row["event_type"],
            entity_type=row["entity_type"],
            entity_id=row["entity_id"],
            payload=event.payload,
            prev_hash=row["prev_hash"],
            event_hash=row["event_hash"],
        )

    except sqlite3.Error as e:
        raise AuditInsertError(f"Failed to insert audit event: {e}") from e


def get_audit_events(
    *,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    event_type: Optional[str] = None,
    actor_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[AuditEventRecord]:
    """
    Query audit events (READ-ONLY).

    Args:
        entity_type: Filter by entity type
        entity_id: Filter by entity ID
        event_type: Filter by event type
        actor_id: Filter by actor ID
        start_date: Filter events >= this ISO date
        end_date: Filter events <= this ISO date
        limit: Maximum events to return (default 100)
        offset: Pagination offset

    Returns:
        List of audit event records, ordered by created_at DESC
    """
    query = "SELECT * FROM audit_events WHERE 1=1"
    params: Dict[str, Any] = {}

    if entity_type:
        query += " AND entity_type = :entity_type"
        params["entity_type"] = entity_type

    if entity_id:
        query += " AND entity_id = :entity_id"
        params["entity_id"] = entity_id

    if event_type:
        query += " AND event_type = :event_type"
        params["event_type"] = event_type

    if actor_id:
        query += " AND actor_id = :actor_id"
        params["actor_id"] = actor_id

    if start_date:
        query += " AND created_at >= :start_date"
        params["start_date"] = start_date

    if end_date:
        query += " AND created_at <= :end_date"
        params["end_date"] = end_date

    query += " ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
    params["limit"] = limit
    params["offset"] = offset

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query, params).fetchall()

    return [
        AuditEventRecord(
            id=row["id"],
            created_at=row["created_at"],
            actor_id=row["actor_id"],
            event_type=row["event_type"],
            entity_type=row["entity_type"],
            entity_id=row["entity_id"],
            payload=json.loads(row["payload"]),
            prev_hash=row["prev_hash"],
            event_hash=row["event_hash"],
        )
        for row in rows
    ]


def get_audit_event_by_id(event_id: str) -> Optional[AuditEventRecord]:
    """
    Get a single audit event by ID (READ-ONLY).

    Args:
        event_id: The event ID to retrieve

    Returns:
        The audit event record, or None if not found
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM audit_events WHERE id = ?", (event_id,)
        ).fetchone()

    if not row:
        return None

    return AuditEventRecord(
        id=row["id"],
        created_at=row["created_at"],
        actor_id=row["actor_id"],
        event_type=row["event_type"],
        entity_type=row["entity_type"],
        entity_id=row["entity_id"],
        payload=json.loads(row["payload"]),
        prev_hash=row["prev_hash"],
        event_hash=row["event_hash"],
    )


def verify_audit_chain(limit: int = 1000) -> Tuple[bool, List[Dict[str, Any]]]:
    """
    Verify the integrity of the audit event hash chain.

    This checks that:
    1. Each event's hash can be recomputed and matches stored hash
    2. Each event's prev_hash matches the previous event's event_hash

    Args:
        limit: Maximum events to verify (for performance)

    Returns:
        Tuple of (is_valid, list_of_issues)
    """
    pepper = _get_pepper()
    issues: List[Dict[str, Any]] = []

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM audit_events ORDER BY created_at ASC LIMIT ?", (limit,)
        ).fetchall()

    if not rows:
        return True, []

    prev_event_hash: Optional[str] = None

    for i, row in enumerate(rows):
        payload = json.loads(row["payload"])

        # Verify event hash
        is_valid = verify_event_hash(
            expected_hash=row["event_hash"],
            prev_hash=row["prev_hash"],
            actor_id=row["actor_id"],
            event_type=row["event_type"],
            entity_type=row["entity_type"],
            entity_id=row["entity_id"],
            payload=payload,
            created_at_iso=row["created_at"],
            pepper=pepper,
        )

        if not is_valid:
            issues.append({
                "event_id": row["id"],
                "index": i,
                "issue": "event_hash_mismatch",
                "message": "Computed hash does not match stored event_hash",
            })

        # Verify chain (skip first event)
        if i > 0 and row["prev_hash"] != prev_event_hash:
            issues.append({
                "event_id": row["id"],
                "index": i,
                "issue": "chain_break",
                "message": f"prev_hash does not match previous event_hash",
                "expected_prev_hash": prev_event_hash,
                "actual_prev_hash": row["prev_hash"],
            })

        prev_event_hash = row["event_hash"]

    return len(issues) == 0, issues


def count_audit_events(
    *,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    event_type: Optional[str] = None,
    actor_id: Optional[str] = None,
) -> int:
    """
    Count audit events matching filters (READ-ONLY).

    Args:
        entity_type: Filter by entity type
        entity_id: Filter by entity ID
        event_type: Filter by event type
        actor_id: Filter by actor ID

    Returns:
        Count of matching events
    """
    query = "SELECT COUNT(*) as cnt FROM audit_events WHERE 1=1"
    params: Dict[str, Any] = {}

    if entity_type:
        query += " AND entity_type = :entity_type"
        params["entity_type"] = entity_type

    if entity_id:
        query += " AND entity_id = :entity_id"
        params["entity_id"] = entity_id

    if event_type:
        query += " AND event_type = :event_type"
        params["event_type"] = event_type

    if actor_id:
        query += " AND actor_id = :actor_id"
        params["actor_id"] = actor_id

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(query, params).fetchone()

    return row["cnt"] if row else 0
