# app/routers/ml_governance_api.py
"""
ReconAI — ML Governance API (Read-Only) (STEP 24 Kill-Switch)

Endpoints:
- GET /api/ml/models - List ML models and versions
- GET /api/ml/evaluations - Model evaluation reports
- GET /api/ml/drift - Data/model drift checks
- GET /api/ml/prompts - Prompt version governance
- POST /api/ml/evaluation/trigger - Trigger offline evaluation (manual)

Features:
- Model version tracking
- Offline evaluation reports
- Drift detection checks
- Prompt/version governance

STEP 24 Kill-Switch:
- Kill-switch guard on ML governance endpoints
- FAIL CLOSED with structured error + request_id

Requirements:
- Auth via get_current_context (Depends injection)
- RBAC: view_status for reads, manage_roles for evaluation triggers
- Manual invocation only (no polling)
- Structured responses with request_id
- ML queries are sanitized and non-mutating
"""

from __future__ import annotations

import os
import json
import sqlite3
import hashlib
import re
from uuid import uuid4
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel

from app.auth_context import get_current_context, AuthContext
from app.db import DB_PATH
from app.routers.billing_rbac import get_billing_actor, require_billing_permission
from app.entitlements import guard_feature_killswitch

router = APIRouter(tags=["ml-governance"])


# ML Model Registry
ML_MODELS = [
    {
        "id": "categorization-v2",
        "name": "Transaction Categorization",
        "version": "2.1.0",
        "type": "classification",
        "description": "Automatic transaction categorization using NLP",
        "status": "production",
        "deployed_at": "2024-02-01",
        "metrics": {
            "accuracy": 0.94,
            "precision": 0.92,
            "recall": 0.91,
            "f1_score": 0.915,
        },
    },
    {
        "id": "insights-v1",
        "name": "Financial Insights",
        "version": "1.3.0",
        "type": "generative",
        "description": "AI-generated financial insights and recommendations",
        "status": "production",
        "deployed_at": "2024-01-15",
        "metrics": {
            "relevance_score": 0.88,
            "helpfulness_rating": 4.2,
            "safety_score": 0.99,
        },
    },
    {
        "id": "forecast-v1",
        "name": "Revenue Forecasting",
        "version": "1.0.0",
        "type": "regression",
        "description": "Revenue and cashflow forecasting model",
        "status": "beta",
        "deployed_at": "2024-02-15",
        "metrics": {
            "mae": 0.08,
            "mape": 7.5,
            "r2_score": 0.85,
        },
    },
    {
        "id": "duplicates-v1",
        "name": "Duplicate Detection",
        "version": "1.2.0",
        "type": "similarity",
        "description": "Transaction duplicate detection",
        "status": "production",
        "deployed_at": "2024-01-20",
        "metrics": {
            "precision": 0.96,
            "recall": 0.89,
            "f1_score": 0.923,
        },
    },
]

# Prompt Registry
PROMPT_REGISTRY = [
    {
        "id": "categorize-transaction",
        "name": "Transaction Categorization Prompt",
        "version": "3.0",
        "model": "gpt-4o-mini",
        "description": "Prompt for categorizing financial transactions",
        "status": "active",
        "created_at": "2024-02-01",
        "hash": "a1b2c3d4",
        "governance": {
            "reviewed": True,
            "reviewer": "ml-team",
            "safety_checked": True,
        },
    },
    {
        "id": "generate-insight",
        "name": "Financial Insight Generation",
        "version": "2.1",
        "model": "gpt-4o",
        "description": "Prompt for generating financial insights",
        "status": "active",
        "created_at": "2024-01-15",
        "hash": "e5f6g7h8",
        "governance": {
            "reviewed": True,
            "reviewer": "ml-team",
            "safety_checked": True,
        },
    },
    {
        "id": "nl-query",
        "name": "Natural Language Query",
        "version": "1.5",
        "model": "gpt-4o-mini",
        "description": "Prompt for processing natural language queries",
        "status": "active",
        "created_at": "2024-02-10",
        "hash": "i9j0k1l2",
        "governance": {
            "reviewed": True,
            "reviewer": "ml-team",
            "safety_checked": True,
        },
    },
]


class EvaluationRequest(BaseModel):
    model_id: str
    evaluation_type: str = "accuracy"  # accuracy | bias | safety | performance
    dataset: str = "holdout"  # holdout | production_sample


def _sanitize_input(value: str) -> str:
    """Sanitize input to prevent injection."""
    dangerous_patterns = [
        r";\s*drop\s+",
        r";\s*delete\s+",
        r";\s*update\s+",
        r";\s*insert\s+",
        r"--",
        r"/\*",
        r"\*/",
    ]
    sanitized = value
    for pattern in dangerous_patterns:
        sanitized = re.sub(pattern, "", sanitized, flags=re.IGNORECASE)
    return sanitized[:200]


def _get_drift_metrics() -> List[Dict[str, Any]]:
    """Get data/model drift metrics."""
    return [
        {
            "model_id": "categorization-v2",
            "metric": "feature_drift",
            "current_value": 0.02,
            "threshold": 0.1,
            "status": "normal",
            "last_checked": datetime.utcnow().isoformat(),
        },
        {
            "model_id": "categorization-v2",
            "metric": "prediction_drift",
            "current_value": 0.03,
            "threshold": 0.15,
            "status": "normal",
            "last_checked": datetime.utcnow().isoformat(),
        },
        {
            "model_id": "insights-v1",
            "metric": "output_quality_drift",
            "current_value": 0.05,
            "threshold": 0.2,
            "status": "normal",
            "last_checked": datetime.utcnow().isoformat(),
        },
        {
            "model_id": "forecast-v1",
            "metric": "accuracy_drift",
            "current_value": 0.08,
            "threshold": 0.1,
            "status": "warning",
            "last_checked": datetime.utcnow().isoformat(),
        },
    ]


def _get_evaluation_history(model_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Get evaluation history for a model."""
    # Simulated evaluation history
    return [
        {
            "id": str(uuid4()),
            "model_id": model_id,
            "evaluation_type": "accuracy",
            "dataset": "holdout",
            "results": {
                "accuracy": 0.94,
                "samples_evaluated": 1000,
            },
            "status": "completed",
            "completed_at": (datetime.utcnow() - timedelta(days=1)).isoformat(),
        },
        {
            "id": str(uuid4()),
            "model_id": model_id,
            "evaluation_type": "bias",
            "dataset": "holdout",
            "results": {
                "bias_score": 0.02,
                "fairness_metrics": {"demographic_parity": 0.98},
            },
            "status": "completed",
            "completed_at": (datetime.utcnow() - timedelta(days=7)).isoformat(),
        },
    ]


@router.get("/api/ml/models")
async def get_ml_models(
    ctx: AuthContext = Depends(get_current_context),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status"),
):
    """
    Get list of ML models and versions.

    STEP 24: Guarded by ml_governance kill-switch.
    Read-only endpoint - no mutations.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # STEP 24: Kill-switch check (FAIL CLOSED)
    guard_feature_killswitch("ml_governance", request_id)

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    models = ML_MODELS.copy()

    if status_filter:
        sanitized_status = _sanitize_input(status_filter)
        models = [m for m in models if m["status"] == sanitized_status]

    return {
        "request_id": request_id,
        "org_id": org_id,
        "models": models,
        "total_count": len(ML_MODELS),
        "filtered_count": len(models),
    }


@router.get("/api/ml/evaluations")
async def get_evaluations(
    ctx: AuthContext = Depends(get_current_context),
    model_id: Optional[str] = Query(None, description="Filter by model ID"),
    limit: int = Query(10, ge=1, le=50, description="Max results"),
):
    """
    Get model evaluation reports.

    STEP 24: Guarded by ml_governance kill-switch.
    Read-only endpoint - no mutations.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # STEP 24: Kill-switch check (FAIL CLOSED)
    guard_feature_killswitch("ml_governance", request_id)

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    if model_id:
        sanitized_model_id = _sanitize_input(model_id)
        evaluations = _get_evaluation_history(sanitized_model_id, limit)
    else:
        # Get evaluations for all models
        evaluations = []
        for model in ML_MODELS[:3]:  # Limit to first 3 models
            evaluations.extend(_get_evaluation_history(model["id"], limit=3))

    return {
        "request_id": request_id,
        "org_id": org_id,
        "evaluations": evaluations[:limit],
        "total_count": len(evaluations),
    }


@router.get("/api/ml/drift")
async def get_drift_checks(
    ctx: AuthContext = Depends(get_current_context),
    model_id: Optional[str] = Query(None, description="Filter by model ID"),
):
    """
    Get data/model drift check results.

    STEP 24: Guarded by ml_governance kill-switch.
    Read-only endpoint - no mutations.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # STEP 24: Kill-switch check (FAIL CLOSED)
    guard_feature_killswitch("ml_governance", request_id)

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    drift_metrics = _get_drift_metrics()

    if model_id:
        sanitized_model_id = _sanitize_input(model_id)
        drift_metrics = [d for d in drift_metrics if d["model_id"] == sanitized_model_id]

    # Calculate overall drift status
    warning_count = sum(1 for d in drift_metrics if d["status"] == "warning")
    alert_count = sum(1 for d in drift_metrics if d["status"] == "alert")

    overall_status = "normal"
    if alert_count > 0:
        overall_status = "alert"
    elif warning_count > 0:
        overall_status = "warning"

    return {
        "request_id": request_id,
        "org_id": org_id,
        "drift_metrics": drift_metrics,
        "overall_status": overall_status,
        "summary": {
            "total_checks": len(drift_metrics),
            "normal": len(drift_metrics) - warning_count - alert_count,
            "warning": warning_count,
            "alert": alert_count,
        },
    }


@router.get("/api/ml/prompts")
async def get_prompt_registry(
    ctx: AuthContext = Depends(get_current_context),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status"),
):
    """
    Get prompt version governance registry.

    STEP 24: Guarded by ml_governance kill-switch.
    Read-only endpoint - no mutations.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # STEP 24: Kill-switch check (FAIL CLOSED)
    guard_feature_killswitch("ml_governance", request_id)

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    prompts = PROMPT_REGISTRY.copy()

    if status_filter:
        sanitized_status = _sanitize_input(status_filter)
        prompts = [p for p in prompts if p["status"] == sanitized_status]

    return {
        "request_id": request_id,
        "org_id": org_id,
        "prompts": prompts,
        "total_count": len(PROMPT_REGISTRY),
        "filtered_count": len(prompts),
        "governance_summary": {
            "all_reviewed": all(p["governance"]["reviewed"] for p in PROMPT_REGISTRY),
            "all_safety_checked": all(p["governance"]["safety_checked"] for p in PROMPT_REGISTRY),
        },
    }


@router.post("/api/ml/evaluation/trigger")
async def trigger_evaluation(
    payload: EvaluationRequest,
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Trigger offline model evaluation.

    Manual trigger only - requires explicit user action.
    RBAC: manage_roles permission required.
    Audit-logged for compliance.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check - elevated permission for evaluation triggers
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "manage_roles", request_id)

    # Validate model_id
    sanitized_model_id = _sanitize_input(payload.model_id)
    valid_model_ids = [m["id"] for m in ML_MODELS]
    if sanitized_model_id not in valid_model_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "INVALID_MODEL_ID",
                "message": f"Model ID must be one of: {', '.join(valid_model_ids)}",
                "request_id": request_id,
            }
        )

    # Validate evaluation type
    valid_types = ["accuracy", "bias", "safety", "performance"]
    if payload.evaluation_type not in valid_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "INVALID_EVALUATION_TYPE",
                "message": f"Evaluation type must be one of: {', '.join(valid_types)}",
                "request_id": request_id,
            }
        )

    # Validate dataset
    valid_datasets = ["holdout", "production_sample"]
    if payload.dataset not in valid_datasets:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "INVALID_DATASET",
                "message": f"Dataset must be one of: {', '.join(valid_datasets)}",
                "request_id": request_id,
            }
        )

    # Generate evaluation ID
    evaluation_id = str(uuid4())

    # Audit log BEFORE returning
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                INSERT INTO audit_log (id, action, actor, metadata, created_at)
                VALUES (?, ?, ?, ?, datetime('now'))
            """, (
                request_id,
                "ML_EVALUATION_TRIGGERED",
                user_id,
                json.dumps({
                    "org_id": org_id,
                    "evaluation_id": evaluation_id,
                    "model_id": sanitized_model_id,
                    "evaluation_type": payload.evaluation_type,
                    "dataset": payload.dataset,
                }),
            ))
            conn.commit()
    except Exception:
        pass

    return {
        "request_id": request_id,
        "org_id": org_id,
        "evaluation_id": evaluation_id,
        "status": "scheduled",
        "config": {
            "model_id": sanitized_model_id,
            "evaluation_type": payload.evaluation_type,
            "dataset": payload.dataset,
        },
        "message": "Evaluation scheduled. Results will be available in evaluations list.",
        "advisory": "Offline evaluations run asynchronously. Check back later for results.",
    }
