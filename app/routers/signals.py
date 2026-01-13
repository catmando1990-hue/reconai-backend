from fastapi import APIRouter, Depends
from app.auth_context import get_current_context

router = APIRouter(prefix="/api")

@router.get("/signals")
def list_signals(ctx=Depends(get_current_context)):
    return [
        {
            "id": "sig_dup_1",
            "type": "duplicate_charge",
            "severity": "warning",
            "entity": "transaction",
            "entity_id": "tx_1",
            "created_at": "2026-01-12T10:15:00Z"
        }
    ]

@router.get("/signals/{signal_id}/evidence")
def signal_evidence(signal_id: str, ctx=Depends(get_current_context)):
    return {
        "signal_id": signal_id,
        "rules": [
            "same_merchant",
            "same_amount",
            "posted_within_48h"
        ],
        "transactions": ["tx_1", "tx_2"]
    }
