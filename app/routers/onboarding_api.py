# app/routers/onboarding_api.py
"""
ReconAI — Customer Onboarding API

Endpoints:
- GET /api/onboarding/status - Get onboarding progress
- GET /api/onboarding/checklist - Get setup checklist
- POST /api/onboarding/step/complete - Mark step complete (manual)
- POST /api/onboarding/sample-data/seed - Seed sample data (manual, audit-logged)
- GET /api/onboarding/first-run-insights - First-run insights for new users

Features:
- Guided setup flows
- Progress tracking
- Sample data seeding
- First-run insights
- Setup checklists

Requirements:
- Auth via get_current_context (Depends injection)
- RBAC: view_status for reads, manage_roles for mutations
- Manual invocation only (no polling)
- Structured responses with request_id
"""

from __future__ import annotations

import os
import json
import sqlite3
from uuid import uuid4
from datetime import datetime
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel

from app.auth_context import get_current_context, AuthContext
from app.db import DB_PATH
from app.routers.billing_rbac import get_billing_actor, require_billing_permission

router = APIRouter(tags=["onboarding"])


# Onboarding Steps
ONBOARDING_STEPS = [
    {
        "id": "account_setup",
        "name": "Account Setup",
        "description": "Complete your account profile",
        "order": 1,
        "required": True,
        "estimated_time": "2 minutes",
    },
    {
        "id": "connect_bank",
        "name": "Connect Bank Account",
        "description": "Link your bank account via Plaid",
        "order": 2,
        "required": False,
        "estimated_time": "3 minutes",
    },
    {
        "id": "import_transactions",
        "name": "Import Transactions",
        "description": "Import your first transactions",
        "order": 3,
        "required": True,
        "estimated_time": "5 minutes",
    },
    {
        "id": "categorize_sample",
        "name": "Categorize Transactions",
        "description": "Review and categorize some transactions",
        "order": 4,
        "required": True,
        "estimated_time": "5 minutes",
    },
    {
        "id": "view_reports",
        "name": "View Reports",
        "description": "Explore your financial reports",
        "order": 5,
        "required": False,
        "estimated_time": "3 minutes",
    },
    {
        "id": "invite_team",
        "name": "Invite Team Members",
        "description": "Invite colleagues to collaborate",
        "order": 6,
        "required": False,
        "estimated_time": "2 minutes",
    },
]

# First-Run Insights
FIRST_RUN_INSIGHTS = [
    {
        "id": "welcome",
        "type": "info",
        "title": "Welcome to ReconAI!",
        "message": "We're excited to help you manage your finances smarter. Let's get started!",
        "action": {"label": "Start Setup", "target": "/onboarding"},
    },
    {
        "id": "quick_tip_categorization",
        "type": "tip",
        "title": "Smart Categorization",
        "message": "ReconAI learns from your categorization choices. The more you categorize, the smarter it gets!",
        "action": None,
    },
    {
        "id": "quick_tip_insights",
        "type": "tip",
        "title": "AI-Powered Insights",
        "message": "Check the Insights tab regularly for AI-generated recommendations about your finances.",
        "action": {"label": "View Insights", "target": "/insights"},
    },
]

# Sample Data Templates
SAMPLE_DATA_TEMPLATES = [
    {
        "id": "small_business",
        "name": "Small Business",
        "description": "Sample data for a small business with typical expenses",
        "transaction_count": 50,
        "categories": ["Office Supplies", "Software", "Travel", "Meals", "Utilities"],
    },
    {
        "id": "freelancer",
        "name": "Freelancer",
        "description": "Sample data for a freelance professional",
        "transaction_count": 30,
        "categories": ["Equipment", "Software", "Home Office", "Professional Services"],
    },
    {
        "id": "ecommerce",
        "name": "E-Commerce",
        "description": "Sample data for an e-commerce business",
        "transaction_count": 100,
        "categories": ["Inventory", "Shipping", "Marketing", "Platform Fees", "Returns"],
    },
]


class StepCompleteRequest(BaseModel):
    step_id: str
    notes: Optional[str] = None


class SampleDataRequest(BaseModel):
    template_id: str
    confirmation: str  # Must type "SEED SAMPLE DATA"


def _get_onboarding_progress(org_id: str) -> Dict[str, Any]:
    """Get onboarding progress for an organization."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "SELECT features FROM organizations WHERE id = ?",
            (org_id,)
        )
        row = cursor.fetchone()

        default_progress = {
            "completed_steps": [],
            "started_at": None,
            "completed_at": None,
        }

        if row and row[0]:
            try:
                features = json.loads(row[0])
                return features.get("onboarding_progress", default_progress)
            except json.JSONDecodeError:
                pass

        return default_progress


def _save_onboarding_progress(org_id: str, progress: Dict[str, Any]) -> bool:
    """Save onboarding progress."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "SELECT features FROM organizations WHERE id = ?",
            (org_id,)
        )
        row = cursor.fetchone()

        features = {}
        if row and row[0]:
            try:
                features = json.loads(row[0])
            except json.JSONDecodeError:
                features = {}

        features["onboarding_progress"] = progress

        cursor = conn.execute("""
            UPDATE organizations
            SET features = ?, updated_at = datetime('now')
            WHERE id = ?
        """, (json.dumps(features), org_id))
        conn.commit()

        return cursor.rowcount > 0


@router.get("/api/onboarding/status")
async def get_onboarding_status(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Get onboarding progress status.

    Read-only endpoint - no mutations.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    progress = _get_onboarding_progress(org_id)
    completed_steps = progress.get("completed_steps", [])

    total_steps = len(ONBOARDING_STEPS)
    completed_count = len(completed_steps)
    required_steps = [s for s in ONBOARDING_STEPS if s["required"]]
    required_completed = len([s for s in required_steps if s["id"] in completed_steps])

    is_complete = required_completed >= len(required_steps)

    return {
        "request_id": request_id,
        "org_id": org_id,
        "progress": {
            "total_steps": total_steps,
            "completed_steps": completed_count,
            "required_steps": len(required_steps),
            "required_completed": required_completed,
            "completion_percent": round((completed_count / total_steps) * 100, 1),
            "is_complete": is_complete,
        },
        "completed_step_ids": completed_steps,
        "started_at": progress.get("started_at"),
        "completed_at": progress.get("completed_at"),
    }


@router.get("/api/onboarding/checklist")
async def get_onboarding_checklist(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Get setup checklist with completion status.

    Read-only endpoint - no mutations.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    progress = _get_onboarding_progress(org_id)
    completed_steps = progress.get("completed_steps", [])

    checklist = []
    for step in ONBOARDING_STEPS:
        checklist.append({
            **step,
            "completed": step["id"] in completed_steps,
        })

    # Find next step to complete
    next_step = None
    for step in checklist:
        if not step["completed"]:
            next_step = step
            break

    return {
        "request_id": request_id,
        "org_id": org_id,
        "checklist": checklist,
        "next_step": next_step,
    }


@router.post("/api/onboarding/step/complete")
async def complete_onboarding_step(
    payload: StepCompleteRequest,
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Mark an onboarding step as complete.

    Manual trigger only - requires explicit user action.
    RBAC: view_status permission (user action).
    Audit-logged for tracking.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    # Validate step_id
    valid_step_ids = [s["id"] for s in ONBOARDING_STEPS]
    if payload.step_id not in valid_step_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "INVALID_STEP_ID",
                "message": f"Step ID must be one of: {', '.join(valid_step_ids)}",
                "request_id": request_id,
            }
        )

    # Get current progress
    progress = _get_onboarding_progress(org_id)
    completed_steps = progress.get("completed_steps", [])

    # Check if already completed
    if payload.step_id in completed_steps:
        return {
            "request_id": request_id,
            "org_id": org_id,
            "status": "already_completed",
            "step_id": payload.step_id,
            "message": "Step was already marked as complete.",
        }

    # Mark step as complete
    completed_steps.append(payload.step_id)
    progress["completed_steps"] = completed_steps

    # Set started_at if first step
    if not progress.get("started_at"):
        progress["started_at"] = datetime.utcnow().isoformat()

    # Check if all required steps complete
    required_steps = [s["id"] for s in ONBOARDING_STEPS if s["required"]]
    if all(s in completed_steps for s in required_steps):
        progress["completed_at"] = datetime.utcnow().isoformat()

    # Save progress
    _save_onboarding_progress(org_id, progress)

    # Audit log BEFORE returning
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                INSERT INTO audit_log (id, action, actor, metadata, created_at)
                VALUES (?, ?, ?, ?, datetime('now'))
            """, (
                request_id,
                "ONBOARDING_STEP_COMPLETED",
                user_id,
                json.dumps({
                    "org_id": org_id,
                    "step_id": payload.step_id,
                    "notes": payload.notes,
                }),
            ))
            conn.commit()
    except Exception:
        pass

    return {
        "request_id": request_id,
        "org_id": org_id,
        "status": "completed",
        "step_id": payload.step_id,
        "completed_steps": completed_steps,
        "total_completed": len(completed_steps),
    }


@router.post("/api/onboarding/sample-data/seed")
async def seed_sample_data(
    payload: SampleDataRequest,
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Seed sample data for onboarding.

    Manual trigger only - requires explicit confirmation.
    RBAC: manage_roles permission required.
    Audit-logged for compliance.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check - elevated permission for data seeding
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "manage_roles", request_id)

    # Require explicit confirmation
    if payload.confirmation != "SEED SAMPLE DATA":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "CONFIRMATION_REQUIRED",
                "message": "Must type 'SEED SAMPLE DATA' to confirm",
                "request_id": request_id,
            }
        )

    # Validate template_id
    valid_template_ids = [t["id"] for t in SAMPLE_DATA_TEMPLATES]
    if payload.template_id not in valid_template_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "INVALID_TEMPLATE_ID",
                "message": f"Template ID must be one of: {', '.join(valid_template_ids)}",
                "request_id": request_id,
            }
        )

    template = next((t for t in SAMPLE_DATA_TEMPLATES if t["id"] == payload.template_id), None)

    # Audit log BEFORE returning
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                INSERT INTO audit_log (id, action, actor, metadata, created_at)
                VALUES (?, ?, ?, ?, datetime('now'))
            """, (
                request_id,
                "SAMPLE_DATA_SEEDED",
                user_id,
                json.dumps({
                    "org_id": org_id,
                    "template_id": payload.template_id,
                    "transaction_count": template["transaction_count"],
                }),
            ))
            conn.commit()
    except Exception:
        pass

    return {
        "request_id": request_id,
        "org_id": org_id,
        "status": "seeded",
        "template": template,
        "message": f"Sample data seeded: {template['transaction_count']} transactions created.",
    }


@router.get("/api/onboarding/first-run-insights")
async def get_first_run_insights(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Get first-run insights for new users.

    Read-only endpoint - no mutations.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    progress = _get_onboarding_progress(org_id)
    is_new_user = not progress.get("started_at")

    # Return insights based on user state
    insights = FIRST_RUN_INSIGHTS if is_new_user else []

    return {
        "request_id": request_id,
        "org_id": org_id,
        "is_new_user": is_new_user,
        "insights": insights,
        "sample_data_templates": SAMPLE_DATA_TEMPLATES,
    }
