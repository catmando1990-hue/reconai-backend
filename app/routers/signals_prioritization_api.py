# signals_prioritization_api.py
# STEP 4C — Signals Prioritization (Deterministic Ranking)
# Ranks signals by recency, impact, confidence.
# NO AI calls — deterministic scoring only.
# User-controlled filters.

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from app.auth_context import get_current_context, AuthContext
from app.db import DB_PATH
from app.entitlements import guard_signals_depth, guard_summary_access, get_tier_limits


router = APIRouter(prefix="/api/signals", tags=["signals-prioritization"])


class SignalPriority(BaseModel):
    """Deterministic signal priority score."""
    signal_id: str
    signal_type: str
    recency_score: float  # 0-1, higher = more recent
    impact_score: float   # 0-1, higher = more impactful
    confidence_score: float  # 0-1, from intelligence result
    composite_score: float  # Weighted combination
    rank: int


# Weight configuration for composite scoring
WEIGHTS = {
    "recency": 0.30,
    "impact": 0.35,
    "confidence": 0.35,
}

# Impact classification by signal type
IMPACT_WEIGHTS = {
    "duplicate_detected": 0.9,      # High impact - potential fraud/error
    "categorization_suggestion": 0.5,  # Medium impact - classification
    "cashflow_warning": 0.85,       # High impact - financial health
    "cashflow_trend": 0.6,          # Medium impact - informational
    "recommendation": 0.4,          # Lower impact - advisory
    "anomaly": 0.95,                # Critical - unusual activity
}


def _calculate_recency_score(created_at: str, max_age_days: int = 30) -> float:
    """
    Calculate recency score (0-1). More recent = higher score.
    Uses exponential decay over max_age_days.
    """
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        now = datetime.now(created.tzinfo) if created.tzinfo else datetime.utcnow()
        age = (now - created).total_seconds() / 86400  # Convert to days

        if age <= 0:
            return 1.0
        if age >= max_age_days:
            return 0.0

        # Exponential decay: score = e^(-age/half_life)
        half_life = max_age_days / 3
        import math
        return math.exp(-age / half_life)
    except Exception:
        return 0.5  # Default if parsing fails


def _calculate_impact_score(signal_type: str) -> float:
    """
    Calculate impact score based on signal type.
    Deterministic mapping, no AI involved.
    """
    return IMPACT_WEIGHTS.get(signal_type, 0.5)


def _calculate_composite_score(
    recency: float,
    impact: float,
    confidence: float,
) -> float:
    """
    Calculate weighted composite score.
    All weights are predetermined — no ML or AI.
    """
    return (
        WEIGHTS["recency"] * recency +
        WEIGHTS["impact"] * impact +
        WEIGHTS["confidence"] * confidence
    )


@router.get("/prioritized")
async def get_prioritized_signals(
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    signal_types: Optional[str] = Query(
        None,
        description="Comma-separated filter: duplicate_detected,categorization_suggestion,cashflow_warning"
    ),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0, description="Minimum confidence filter"),
    max_age_days: int = Query(30, ge=1, le=90, description="Maximum age in days"),
    limit: int = Query(50, ge=1, le=200, description="Max results"),
):
    """
    GET /api/signals/prioritized

    Returns signals ranked by deterministic priority score.
    Composite score = 30% recency + 35% impact + 35% confidence.

    NO AI calls — all scoring is deterministic.
    User-controlled filters for signal types, confidence, and age.
    STEP 5: Signals depth gated by tier.
    """
    # STEP 5: Apply tier-based depth limit
    tier = ctx.get("tier", "free")
    effective_limit = guard_signals_depth(
        user_id=ctx["user_id"],
        org_id=ctx.get("org_id"),
        tier=tier,
        requested_limit=limit,
        request=request,
    )
    tier_limits = get_tier_limits(tier)

    # Parse signal type filter
    type_filter = None
    if signal_types:
        type_filter = [t.strip() for t in signal_types.split(",") if t.strip()]

    # Fetch evidence refs (signals) from database
    signals = []
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row

            # Build query with optional type filter
            query = """
                SELECT id, result_type, result_id, confidence, explanation, created_at
                FROM evidence_refs
                WHERE user_id = ?
                AND confidence >= ?
            """
            params: List = [ctx["user_id"], min_confidence]

            if type_filter:
                placeholders = ",".join("?" * len(type_filter))
                query += f" AND result_type IN ({placeholders})"
                params.extend(type_filter)

            # Filter by age
            cutoff = (datetime.utcnow() - timedelta(days=max_age_days)).isoformat()
            query += " AND created_at >= ?"
            params.append(cutoff)

            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(effective_limit * 2)  # Fetch extra for re-ranking

            cursor = conn.execute(query, params)
            signals = [dict(row) for row in cursor.fetchall()]
    except Exception:
        pass  # Return empty if table doesn't exist yet

    # Calculate priority scores
    scored_signals = []
    for signal in signals:
        recency = _calculate_recency_score(signal["created_at"], max_age_days)
        impact = _calculate_impact_score(signal["result_type"])
        confidence = signal["confidence"]
        composite = _calculate_composite_score(recency, impact, confidence)

        scored_signals.append({
            "signal_id": signal["id"],
            "signal_type": signal["result_type"],
            "result_id": signal["result_id"],
            "explanation": signal.get("explanation"),
            "created_at": signal["created_at"],
            "recency_score": round(recency, 3),
            "impact_score": round(impact, 3),
            "confidence_score": round(confidence, 3),
            "composite_score": round(composite, 3),
        })

    # Sort by composite score (descending) and assign ranks
    scored_signals.sort(key=lambda x: x["composite_score"], reverse=True)
    for i, signal in enumerate(scored_signals[:effective_limit]):
        signal["rank"] = i + 1

    # STEP 5: Include tier info in response
    was_capped = limit > effective_limit
    return {
        "ok": True,
        "signals": scored_signals[:effective_limit],
        "total_count": len(scored_signals),
        "returned_count": min(len(scored_signals), effective_limit),
        "filters_applied": {
            "signal_types": type_filter,
            "min_confidence": min_confidence,
            "max_age_days": max_age_days,
        },
        "scoring_weights": WEIGHTS,
        "tier_info": {
            "current_tier": tier,
            "tier_limit": tier_limits.signals_depth,
            "requested_limit": limit,
            "effective_limit": effective_limit,
            "was_capped": was_capped,
            "upgrade_for_more": was_capped,
        },
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/summary")
async def get_signals_summary(
    request: Request,
    ctx: AuthContext = Depends(get_current_context),
    max_age_days: int = Query(30, ge=1, le=90, description="Maximum age in days"),
):
    """
    GET /api/signals/summary

    Returns summary statistics for user's signals.
    Useful for dashboard widgets and overview panels.
    STEP 5: Gated by tier entitlement.
    """
    # STEP 5: Check tier entitlement for summary
    tier = ctx.get("tier", "free")
    guard_summary_access(
        user_id=ctx["user_id"],
        org_id=ctx.get("org_id"),
        tier=tier,
        request=request,
    )

    summary = {
        "total_signals": 0,
        "by_type": {},
        "high_priority_count": 0,  # composite >= 0.7
        "avg_confidence": 0.0,
    }

    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row

            cutoff = (datetime.utcnow() - timedelta(days=max_age_days)).isoformat()

            # Count by type
            cursor = conn.execute("""
                SELECT result_type, COUNT(*) as count, AVG(confidence) as avg_conf
                FROM evidence_refs
                WHERE user_id = ? AND created_at >= ?
                GROUP BY result_type
            """, (ctx["user_id"], cutoff))

            total = 0
            total_conf = 0.0
            for row in cursor.fetchall():
                summary["by_type"][row["result_type"]] = {
                    "count": row["count"],
                    "avg_confidence": round(row["avg_conf"], 3),
                }
                total += row["count"]
                total_conf += row["avg_conf"] * row["count"]

            summary["total_signals"] = total
            if total > 0:
                summary["avg_confidence"] = round(total_conf / total, 3)

            # Count high priority (fetch and score)
            cursor = conn.execute("""
                SELECT result_type, confidence, created_at
                FROM evidence_refs
                WHERE user_id = ? AND created_at >= ?
            """, (ctx["user_id"], cutoff))

            high_priority = 0
            for row in cursor.fetchall():
                recency = _calculate_recency_score(row["created_at"], max_age_days)
                impact = _calculate_impact_score(row["result_type"])
                composite = _calculate_composite_score(recency, impact, row["confidence"])
                if composite >= 0.7:
                    high_priority += 1

            summary["high_priority_count"] = high_priority

    except Exception:
        pass

    return {
        "ok": True,
        "summary": summary,
        "max_age_days": max_age_days,
        "timestamp": datetime.utcnow().isoformat(),
    }
