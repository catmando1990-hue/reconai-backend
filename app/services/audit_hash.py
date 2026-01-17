# app/services/audit_hash.py
"""
Audit Event Hash Computation for DCAA-Compliant Hash Chaining

This module computes deterministic SHA-256 hashes for audit events,
enabling tamper-evident chain verification. Each event's hash incorporates
the previous event's hash, creating an immutable chain.

CANONICAL LAWS ENFORCED:
- Deterministic JSON serialization (sorted keys, no whitespace)
- Optional HMAC-SHA256 with pepper (AUDIT_HASH_SECRET env var)
- Chain integrity: each event_hash depends on prev_hash

DCAA REQUIREMENTS:
- Audit trail must be tamper-evident
- Records must be verifiable for integrity
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Dict, Optional


def _canonical_json(obj: Any) -> str:
    """
    Produce deterministic JSON: sorted keys, no whitespace, stable floats/ints.

    This ensures identical inputs always produce identical hashes,
    regardless of dict insertion order.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_event_hash(
    *,
    prev_hash: Optional[str],
    actor_id: str,
    event_type: str,
    entity_type: str,
    entity_id: Optional[str],
    payload: Dict[str, Any],
    created_at_iso: str,
    pepper: Optional[str] = None,
) -> str:
    """
    Compute SHA-256 hash for an audit event.

    Args:
        prev_hash: Hash of the previous event (None for first event)
        actor_id: User/system ID that performed the action
        event_type: Type of event (e.g., 'contract_created')
        entity_type: Type of entity affected (e.g., 'contract')
        entity_id: ID of the entity affected (optional)
        payload: Event payload data (must be JSON-serializable)
        created_at_iso: ISO 8601 timestamp of event creation
        pepper: Optional secret for HMAC-SHA256 (from AUDIT_HASH_SECRET env)

    Returns:
        64-character hex string (SHA-256 hash)

    Security Notes:
        - If pepper is provided, uses HMAC-SHA256 to prevent hash recomputation
          by attackers who gain read access to the database.
        - Without pepper, uses plain SHA-256 (still tamper-evident, but
          attackers could theoretically recompute valid hashes).
    """
    base = {
        "prev_hash": prev_hash or "",
        "actor_id": actor_id,
        "event_type": event_type,
        "entity_type": entity_type,
        "entity_id": entity_id or "",
        "payload": payload,
        "created_at": created_at_iso,
    }
    msg = _canonical_json(base).encode("utf-8")

    if pepper:
        # HMAC-SHA256 prevents attackers from recomputing hashes if DB is leaked.
        return hmac.new(pepper.encode("utf-8"), msg, hashlib.sha256).hexdigest()

    return hashlib.sha256(msg).hexdigest()


def verify_event_hash(
    *,
    expected_hash: str,
    prev_hash: Optional[str],
    actor_id: str,
    event_type: str,
    entity_type: str,
    entity_id: Optional[str],
    payload: Dict[str, Any],
    created_at_iso: str,
    pepper: Optional[str] = None,
) -> bool:
    """
    Verify that an event's hash matches expected value.

    Returns:
        True if computed hash matches expected_hash, False otherwise.
    """
    computed = compute_event_hash(
        prev_hash=prev_hash,
        actor_id=actor_id,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        payload=payload,
        created_at_iso=created_at_iso,
        pepper=pepper,
    )
    return hmac.compare_digest(computed, expected_hash)
