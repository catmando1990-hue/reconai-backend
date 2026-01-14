"""
Admin Actions API - Sophisticated diagnostic and fix capabilities
BUILD 28-30: Admin-only endpoints for system management

These endpoints provide real fix actions that can be triggered by
the admin dashboard's AI diagnostic agents.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, Literal
from datetime import datetime
import asyncio
import os
import httpx
import secrets
import string
from datetime import timedelta

from app.auth.context import get_current_context, AuthContext

router = APIRouter(prefix="/api/admin", tags=["Admin Actions"])


class FixAction(BaseModel):
    action: Literal[
        "clear_cache",
        "restart_service",
        "trigger_redeploy",
        "reset_connections",
        "flush_sessions",
        "optimize_db",
        "rotate_tokens",
        "sync_plaid",
    ]
    target: Optional[str] = None
    params: Optional[dict] = None


class FixApprovalRequest(BaseModel):
    """Request to approve and execute a fix action"""
    action: str
    confirmation_code: str  # Must match generated code from diagnostic
    admin_notes: Optional[str] = None


class PendingFix(BaseModel):
    """A fix action pending admin approval"""
    fix_id: str
    action: str
    description: str
    risk: str
    downtime: str
    confirmation_code: str  # 6-char code admin must enter
    expires_at: str
    source_diagnostic: str  # Which diagnostic recommended this


# In-memory store for pending fixes (production would use Redis/DB)
# Key: fix_id, Value: PendingFix data + created_by
_pending_fixes: dict[str, dict] = {}


class DiagnosticRequest(BaseModel):
    type: Literal["health", "performance", "security", "bugs"]
    depth: Literal["quick", "standard", "deep"] = "standard"
    include_fixes: bool = True


class DiagnosticResult(BaseModel):
    type: str
    status: Literal["healthy", "warning", "critical"]
    score: int  # 0-100
    findings: list[dict]
    recommended_fixes: list[dict]
    pending_fixes: list[dict] = []  # Fixes created for admin approval
    timestamp: str


def assert_admin(ctx: AuthContext):
    """Ensure the user has admin privileges"""
    if not ctx.permissions or ctx.permissions.role not in ["admin", "owner"]:
        raise HTTPException(status_code=403, detail="Admin access required")


def generate_confirmation_code() -> str:
    """Generate a 6-character alphanumeric confirmation code"""
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(6))


def create_pending_fix(
    action: str,
    description: str,
    risk: str,
    downtime: str,
    source_diagnostic: str,
    admin_user_id: str,
) -> dict:
    """Create a pending fix that requires admin approval to execute"""
    fix_id = secrets.token_urlsafe(12)
    confirmation_code = generate_confirmation_code()
    expires_at = datetime.utcnow() + timedelta(minutes=30)  # 30 min expiry

    pending_fix = {
        "fix_id": fix_id,
        "action": action,
        "description": description,
        "risk": risk,
        "downtime": downtime,
        "confirmation_code": confirmation_code,
        "expires_at": expires_at.isoformat(),
        "source_diagnostic": source_diagnostic,
        "created_by": admin_user_id,
        "created_at": datetime.utcnow().isoformat(),
        "status": "pending",
    }

    _pending_fixes[fix_id] = pending_fix
    return pending_fix


def cleanup_expired_fixes():
    """Remove expired pending fixes"""
    now = datetime.utcnow()
    expired = [
        fix_id for fix_id, fix in _pending_fixes.items()
        if datetime.fromisoformat(fix["expires_at"]) < now
    ]
    for fix_id in expired:
        del _pending_fixes[fix_id]


# ============================================================================
# HEALTH DIAGNOSTIC AGENT
# ============================================================================

@router.post("/diagnose/health", response_model=DiagnosticResult)
async def diagnose_health(
    request: DiagnosticRequest,
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Sophisticated health diagnostic agent.
    Performs deep analysis of all system components.
    """
    assert_admin(ctx)

    findings = []
    fixes = []
    score = 100

    # Check database connection pool
    try:
        from app.db import get_db_pool_stats
        pool_stats = await get_db_pool_stats()
        if pool_stats.get("available", 0) < 2:
            findings.append({
                "component": "Database Pool",
                "severity": "warning",
                "message": f"Low available connections: {pool_stats.get('available', 0)}",
                "details": pool_stats,
            })
            fixes.append({
                "action": "reset_connections",
                "description": "Reset database connection pool",
                "risk": "low",
                "downtime": "none",
            })
            score -= 15
    except Exception as e:
        findings.append({
            "component": "Database Pool",
            "severity": "error",
            "message": f"Could not check pool: {str(e)}",
        })
        score -= 25

    # Check memory usage
    try:
        import psutil
        memory = psutil.virtual_memory()
        if memory.percent > 85:
            findings.append({
                "component": "Memory",
                "severity": "critical",
                "message": f"High memory usage: {memory.percent}%",
                "details": {"used_gb": memory.used / (1024**3), "total_gb": memory.total / (1024**3)},
            })
            fixes.append({
                "action": "clear_cache",
                "description": "Clear application caches to free memory",
                "risk": "low",
                "downtime": "none",
            })
            score -= 30
        elif memory.percent > 70:
            findings.append({
                "component": "Memory",
                "severity": "warning",
                "message": f"Elevated memory usage: {memory.percent}%",
            })
            score -= 10
    except ImportError:
        pass  # psutil not available

    # Check external service connectivity
    services = [
        ("Clerk", "https://api.clerk.com/v1/health", "Authentication"),
        ("Plaid", "https://production.plaid.com/health", "Banking"),
    ]

    async with httpx.AsyncClient(timeout=5.0) as client:
        for name, url, category in services:
            try:
                resp = await client.get(url)
                if resp.status_code != 200:
                    findings.append({
                        "component": name,
                        "severity": "warning",
                        "message": f"{name} returned status {resp.status_code}",
                    })
                    score -= 10
            except Exception as e:
                findings.append({
                    "component": name,
                    "severity": "error",
                    "message": f"Cannot reach {name}: {str(e)[:100]}",
                })
                score -= 20

    # Determine overall status
    status = "healthy" if score >= 80 else "warning" if score >= 50 else "critical"

    # Create pending fixes for each recommended fix (require admin approval)
    cleanup_expired_fixes()
    pending_fixes = []
    if request.include_fixes and fixes:
        for fix in fixes:
            pending = create_pending_fix(
                action=fix["action"],
                description=fix["description"],
                risk=fix["risk"],
                downtime=fix["downtime"],
                source_diagnostic="health",
                admin_user_id=ctx.user_id or "unknown",
            )
            pending_fixes.append({
                "fix_id": pending["fix_id"],
                "action": pending["action"],
                "description": pending["description"],
                "risk": pending["risk"],
                "downtime": pending["downtime"],
                "confirmation_code": pending["confirmation_code"],
                "expires_at": pending["expires_at"],
            })

    return DiagnosticResult(
        type="health",
        status=status,
        score=max(0, score),
        findings=findings,
        recommended_fixes=fixes,
        pending_fixes=pending_fixes,
        timestamp=datetime.utcnow().isoformat(),
    )


# ============================================================================
# PERFORMANCE DIAGNOSTIC AGENT
# ============================================================================

@router.post("/diagnose/performance", response_model=DiagnosticResult)
async def diagnose_performance(
    request: DiagnosticRequest,
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Sophisticated performance diagnostic agent.
    Analyzes response times, query performance, and resource utilization.
    """
    assert_admin(ctx)

    findings = []
    fixes = []
    score = 100

    # Check average response times from metrics (if available)
    try:
        from app.metrics import get_response_time_stats
        stats = await get_response_time_stats()
        avg_ms = stats.get("avg_ms", 0)
        p99_ms = stats.get("p99_ms", 0)

        if p99_ms > 2000:
            findings.append({
                "component": "API Response Time",
                "severity": "critical",
                "message": f"P99 latency is {p99_ms}ms (target: <500ms)",
                "details": stats,
            })
            fixes.append({
                "action": "optimize_db",
                "description": "Run database query optimizer",
                "risk": "low",
                "downtime": "none",
            })
            score -= 30
        elif p99_ms > 500:
            findings.append({
                "component": "API Response Time",
                "severity": "warning",
                "message": f"P99 latency elevated: {p99_ms}ms",
            })
            score -= 15
    except Exception:
        findings.append({
            "component": "Metrics",
            "severity": "info",
            "message": "Performance metrics not available",
        })

    # Check for slow queries
    try:
        from app.db import get_slow_queries
        slow_queries = await get_slow_queries(threshold_ms=100)
        if slow_queries:
            findings.append({
                "component": "Database Queries",
                "severity": "warning",
                "message": f"Found {len(slow_queries)} slow queries (>100ms)",
                "details": {"queries": slow_queries[:5]},  # Top 5
            })
            fixes.append({
                "action": "optimize_db",
                "description": "Analyze and optimize slow queries",
                "risk": "low",
                "downtime": "none",
            })
            score -= 10 * min(len(slow_queries), 3)
    except Exception:
        pass

    # Check cache hit rate
    try:
        from app.cache import get_cache_stats
        cache_stats = await get_cache_stats()
        hit_rate = cache_stats.get("hit_rate", 1.0)
        if hit_rate < 0.7:
            findings.append({
                "component": "Cache",
                "severity": "warning",
                "message": f"Low cache hit rate: {hit_rate*100:.1f}%",
            })
            fixes.append({
                "action": "clear_cache",
                "description": "Clear and rebuild cache",
                "risk": "low",
                "downtime": "momentary",
            })
            score -= 15
    except Exception:
        pass

    status = "healthy" if score >= 80 else "warning" if score >= 50 else "critical"

    # Create pending fixes for each recommended fix (require admin approval)
    cleanup_expired_fixes()
    pending_fixes = []
    if request.include_fixes and fixes:
        for fix in fixes:
            pending = create_pending_fix(
                action=fix["action"],
                description=fix["description"],
                risk=fix["risk"],
                downtime=fix["downtime"],
                source_diagnostic="performance",
                admin_user_id=ctx.user_id or "unknown",
            )
            pending_fixes.append({
                "fix_id": pending["fix_id"],
                "action": pending["action"],
                "description": pending["description"],
                "risk": pending["risk"],
                "downtime": pending["downtime"],
                "confirmation_code": pending["confirmation_code"],
                "expires_at": pending["expires_at"],
            })

    return DiagnosticResult(
        type="performance",
        status=status,
        score=max(0, score),
        findings=findings,
        recommended_fixes=fixes,
        pending_fixes=pending_fixes,
        timestamp=datetime.utcnow().isoformat(),
    )


# ============================================================================
# SECURITY DIAGNOSTIC AGENT
# ============================================================================

@router.post("/diagnose/security", response_model=DiagnosticResult)
async def diagnose_security(
    request: DiagnosticRequest,
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Sophisticated security diagnostic agent.
    Analyzes authentication, authorization, and potential vulnerabilities.
    """
    assert_admin(ctx)

    findings = []
    fixes = []
    score = 100

    # Check for failed login attempts
    try:
        from app.audit import get_failed_logins
        failed_logins = await get_failed_logins(hours=24)
        if failed_logins > 100:
            findings.append({
                "component": "Authentication",
                "severity": "critical",
                "message": f"High number of failed logins: {failed_logins} in last 24h",
                "details": {"count": failed_logins, "threshold": 100},
            })
            fixes.append({
                "action": "rotate_tokens",
                "description": "Rotate API tokens and invalidate suspicious sessions",
                "risk": "medium",
                "downtime": "users may need to re-login",
            })
            score -= 30
        elif failed_logins > 50:
            findings.append({
                "component": "Authentication",
                "severity": "warning",
                "message": f"Elevated failed logins: {failed_logins}",
            })
            score -= 10
    except Exception:
        pass

    # Check token expiration settings
    token_expiry_hours = int(os.getenv("JWT_EXPIRY_HOURS", "24"))
    if token_expiry_hours > 168:  # More than 1 week
        findings.append({
            "component": "Token Policy",
            "severity": "warning",
            "message": f"Long token expiry: {token_expiry_hours} hours",
            "details": {"recommended": "24-72 hours"},
        })
        score -= 10

    # Check for admin users without MFA
    try:
        from app.users import get_admins_without_mfa
        admins_no_mfa = await get_admins_without_mfa()
        if admins_no_mfa:
            findings.append({
                "component": "MFA",
                "severity": "warning",
                "message": f"{len(admins_no_mfa)} admin users without MFA enabled",
                "details": {"user_ids": admins_no_mfa},
            })
            score -= 15
    except Exception:
        pass

    # Check CORS configuration
    cors_origins = os.getenv("CORS_ORIGINS", "")
    if "*" in cors_origins:
        findings.append({
            "component": "CORS",
            "severity": "critical",
            "message": "CORS allows all origins (*)",
            "details": {"current": cors_origins},
        })
        score -= 25

    # Check for exposed debug endpoints in production
    if os.getenv("ENVIRONMENT", "development") == "production":
        if os.getenv("DEBUG", "false").lower() == "true":
            findings.append({
                "component": "Debug Mode",
                "severity": "critical",
                "message": "Debug mode enabled in production",
            })
            score -= 30

    status = "healthy" if score >= 80 else "warning" if score >= 50 else "critical"

    # Create pending fixes for each recommended fix (require admin approval)
    cleanup_expired_fixes()
    pending_fixes = []
    if request.include_fixes and fixes:
        for fix in fixes:
            pending = create_pending_fix(
                action=fix["action"],
                description=fix["description"],
                risk=fix["risk"],
                downtime=fix["downtime"],
                source_diagnostic="security",
                admin_user_id=ctx.user_id or "unknown",
            )
            pending_fixes.append({
                "fix_id": pending["fix_id"],
                "action": pending["action"],
                "description": pending["description"],
                "risk": pending["risk"],
                "downtime": pending["downtime"],
                "confirmation_code": pending["confirmation_code"],
                "expires_at": pending["expires_at"],
            })

    return DiagnosticResult(
        type="security",
        status=status,
        score=max(0, score),
        findings=findings,
        recommended_fixes=fixes,
        pending_fixes=pending_fixes,
        timestamp=datetime.utcnow().isoformat(),
    )


# ============================================================================
# BUG DETECTION AGENT
# ============================================================================

@router.post("/diagnose/bugs", response_model=DiagnosticResult)
async def diagnose_bugs(
    request: DiagnosticRequest,
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Sophisticated bug detection agent.
    Analyzes error logs, exceptions, and anomalies.
    """
    assert_admin(ctx)

    findings = []
    fixes = []
    score = 100

    # Check recent error logs
    try:
        from app.logging import get_recent_errors
        errors = await get_recent_errors(hours=24)

        # Group by error type
        error_groups = {}
        for err in errors:
            key = err.get("type", "Unknown")
            if key not in error_groups:
                error_groups[key] = []
            error_groups[key].append(err)

        for error_type, instances in error_groups.items():
            severity = "critical" if len(instances) > 50 else "warning" if len(instances) > 10 else "info"
            if severity != "info":
                findings.append({
                    "component": "Error Logs",
                    "severity": severity,
                    "message": f"{error_type}: {len(instances)} occurrences in 24h",
                    "details": {
                        "sample": instances[0] if instances else None,
                        "count": len(instances),
                    },
                })
                if severity == "critical":
                    score -= 25
                else:
                    score -= 10
    except Exception:
        findings.append({
            "component": "Error Logs",
            "severity": "info",
            "message": "Error log analysis not available",
        })

    # Check for unhandled exceptions (via Sentry if configured)
    sentry_dsn = os.getenv("SENTRY_DSN")
    if not sentry_dsn:
        findings.append({
            "component": "Error Tracking",
            "severity": "warning",
            "message": "Sentry not configured - errors may go untracked",
        })
        fixes.append({
            "action": "configure_sentry",
            "description": "Set up Sentry for error tracking",
            "risk": "none",
            "downtime": "none",
        })
        score -= 10

    # Check for deprecated API usage
    try:
        from app.deprecation import check_deprecated_usage
        deprecated = await check_deprecated_usage()
        if deprecated:
            findings.append({
                "component": "Deprecated APIs",
                "severity": "warning",
                "message": f"Found {len(deprecated)} deprecated API usages",
                "details": {"endpoints": deprecated},
            })
            score -= 5
    except Exception:
        pass

    status = "healthy" if score >= 80 else "warning" if score >= 50 else "critical"

    # Create pending fixes for each recommended fix (require admin approval)
    cleanup_expired_fixes()
    pending_fixes = []
    if request.include_fixes and fixes:
        for fix in fixes:
            pending = create_pending_fix(
                action=fix["action"],
                description=fix["description"],
                risk=fix["risk"],
                downtime=fix["downtime"],
                source_diagnostic="bugs",
                admin_user_id=ctx.user_id or "unknown",
            )
            pending_fixes.append({
                "fix_id": pending["fix_id"],
                "action": pending["action"],
                "description": pending["description"],
                "risk": pending["risk"],
                "downtime": pending["downtime"],
                "confirmation_code": pending["confirmation_code"],
                "expires_at": pending["expires_at"],
            })

    return DiagnosticResult(
        type="bugs",
        status=status,
        score=max(0, score),
        findings=findings,
        recommended_fixes=fixes,
        pending_fixes=pending_fixes,
        timestamp=datetime.utcnow().isoformat(),
    )


# ============================================================================
# FIX ACTION ENDPOINTS
# ============================================================================


@router.get("/fixes/pending")
async def get_pending_fixes(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Get all pending fixes awaiting admin approval.
    Admins must approve fixes before they can be executed.
    """
    assert_admin(ctx)
    cleanup_expired_fixes()

    return {
        "pending_fixes": [
            {
                "fix_id": fix["fix_id"],
                "action": fix["action"],
                "description": fix["description"],
                "risk": fix["risk"],
                "downtime": fix["downtime"],
                "confirmation_code": fix["confirmation_code"],
                "expires_at": fix["expires_at"],
                "source_diagnostic": fix["source_diagnostic"],
                "created_at": fix["created_at"],
            }
            for fix in _pending_fixes.values()
            if fix["status"] == "pending"
        ],
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.post("/fixes/{fix_id}/approve")
async def approve_and_execute_fix(
    fix_id: str,
    approval: FixApprovalRequest,
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Approve and execute a pending fix.

    IMPORTANT: Fixes CANNOT execute without explicit admin approval.
    Admin must provide the confirmation_code displayed in the diagnostic.

    This is a critical safety mechanism - AI diagnostic agents can
    recommend fixes, but they cannot act autonomously.
    """
    assert_admin(ctx)
    cleanup_expired_fixes()

    # Find the pending fix
    if fix_id not in _pending_fixes:
        raise HTTPException(
            status_code=404,
            detail="Fix not found or expired. Re-run diagnostic to generate new fix."
        )

    pending_fix = _pending_fixes[fix_id]

    if pending_fix["status"] != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Fix already {pending_fix['status']}"
        )

    # Verify confirmation code (case-insensitive)
    if approval.confirmation_code.upper() != pending_fix["confirmation_code"]:
        raise HTTPException(
            status_code=403,
            detail="Invalid confirmation code. Check the code from the diagnostic results."
        )

    # Verify the action matches
    if approval.action != pending_fix["action"]:
        raise HTTPException(
            status_code=400,
            detail=f"Action mismatch. Expected '{pending_fix['action']}', got '{approval.action}'"
        )

    # Check expiration
    if datetime.fromisoformat(pending_fix["expires_at"]) < datetime.utcnow():
        del _pending_fixes[fix_id]
        raise HTTPException(
            status_code=410,
            detail="Fix approval has expired. Re-run diagnostic to generate new fix."
        )

    # Execute the fix
    result = {
        "fix_id": fix_id,
        "action": pending_fix["action"],
        "success": False,
        "message": "",
        "approved_by": ctx.user_id,
        "admin_notes": approval.admin_notes,
        "timestamp": datetime.utcnow().isoformat(),
    }

    try:
        action = pending_fix["action"]

        if action == "clear_cache":
            try:
                from app.cache import clear_all_caches
                await clear_all_caches()
                result["success"] = True
                result["message"] = "All caches cleared successfully"
            except ImportError:
                result["message"] = "Cache module not available"

        elif action == "reset_connections":
            try:
                from app.db import reset_connection_pool
                await reset_connection_pool()
                result["success"] = True
                result["message"] = "Database connection pool reset"
            except ImportError:
                result["message"] = "Database pool reset not available"

        elif action == "flush_sessions":
            result["message"] = "Session flush requires Clerk dashboard"
            result["success"] = False

        elif action == "optimize_db":
            try:
                from app.db import run_vacuum_analyze
                await run_vacuum_analyze()
                result["success"] = True
                result["message"] = "Database optimization complete"
            except ImportError:
                result["message"] = "Database optimization not available"

        elif action == "sync_plaid":
            try:
                from app.plaid import trigger_sync
                await trigger_sync(ctx.org_id)
                result["success"] = True
                result["message"] = "Plaid sync triggered"
            except ImportError:
                result["message"] = "Plaid sync not available"

        elif action == "trigger_redeploy":
            deploy_hook = os.getenv("RENDER_DEPLOY_HOOK")
            if deploy_hook:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(deploy_hook)
                    if resp.status_code == 200:
                        result["success"] = True
                        result["message"] = "Redeploy triggered successfully"
                    else:
                        result["message"] = f"Redeploy failed: {resp.status_code}"
            else:
                result["message"] = "RENDER_DEPLOY_HOOK not configured"

        elif action == "rotate_tokens":
            result["message"] = "Token rotation requires manual intervention via Clerk dashboard"
            result["success"] = False

        else:
            result["message"] = f"Unknown action: {action}"

        # Mark fix as executed
        pending_fix["status"] = "executed" if result["success"] else "failed"
        pending_fix["executed_at"] = datetime.utcnow().isoformat()
        pending_fix["executed_by"] = ctx.user_id

    except Exception as e:
        result["message"] = f"Fix failed: {str(e)}"
        pending_fix["status"] = "failed"

    return result


@router.delete("/fixes/{fix_id}")
async def cancel_pending_fix(
    fix_id: str,
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Cancel a pending fix (remove without executing).
    """
    assert_admin(ctx)

    if fix_id not in _pending_fixes:
        raise HTTPException(status_code=404, detail="Fix not found")

    del _pending_fixes[fix_id]

    return {
        "message": "Fix cancelled",
        "fix_id": fix_id,
        "cancelled_by": ctx.user_id,
        "timestamp": datetime.utcnow().isoformat(),
    }


# Legacy endpoint - kept for backwards compatibility but requires approval flow
@router.post("/fix")
async def execute_fix(
    action: FixAction,
    ctx: AuthContext = Depends(get_current_context),
):
    """
    DEPRECATED: Direct fix execution is no longer supported.

    All fixes must now go through the approval flow:
    1. Run a diagnostic (/diagnose/health, /diagnose/performance, etc.)
    2. Review pending fixes from the diagnostic results
    3. Approve and execute via POST /fixes/{fix_id}/approve

    This endpoint now only returns instructions on how to use the new flow.
    """
    assert_admin(ctx)

    return {
        "success": False,
        "message": "Direct fix execution is disabled. Fixes require explicit admin approval.",
        "instructions": {
            "step_1": "Run a diagnostic: POST /api/admin/diagnose/health (or performance, security, bugs)",
            "step_2": "Review the pending_fixes in the response - each has a confirmation_code",
            "step_3": "Approve and execute: POST /api/admin/fixes/{fix_id}/approve with the confirmation_code",
        },
        "reason": "AI diagnostic agents cannot act autonomously. Human admin approval is required.",
        "timestamp": datetime.utcnow().isoformat(),
    }
