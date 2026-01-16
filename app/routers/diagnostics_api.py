"""
STEP A — Diagnostics API (Admin-Only, Manual-Run)

Canonical implementation for AI-Powered Diagnostics:
- GET /api/diagnostics/status: Available agents + last_run metadata
- POST /api/diagnostics/run: Manual-run with confirmation phrase
- GET /api/diagnostics/last: Last result snapshot (optional)

RBAC:
- view_status: Can see status (any authenticated user with view access)
- manage_roles: Required for POST /run (ADMIN-only)

Security:
- All endpoints require authentication via get_current_context
- POST /run rate limited to 5/min/org
- Confirmation phrases enforced (fail closed)
- Timeouts on all checks (5s)
- No secrets/PII in outputs

Manual-first UX:
- No polling/timers
- Explicit run required
- request_id in all responses
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional, Literal, Dict, Any
from datetime import datetime, timedelta
import uuid
import time
import os
import httpx

from app.auth_context import get_current_context, AuthContext

router = APIRouter(prefix="/api/diagnostics", tags=["Diagnostics"])


# ============================================================================
# CONFIRMATION PHRASES — FAIL CLOSED
# ============================================================================

CONFIRMATION_PHRASES: Dict[str, str] = {
    "health": "RUN HEALTH AGENT",
    "performance": "RUN PERFORMANCE AGENT",
    "security": "RUN SECURITY AGENT",
    "bug_detection": "RUN BUG DETECTION AGENT",
}


# ============================================================================
# RATE LIMITING — 5 runs/min/org
# ============================================================================

# In-memory rate limit tracking (production: use Redis)
_rate_limits: Dict[str, list] = {}
RATE_LIMIT_MAX = 5
RATE_LIMIT_WINDOW = 60  # seconds


def _check_rate_limit(org_id: str) -> bool:
    """Check if org has exceeded rate limit. Returns True if limited."""
    key = f"diagnostics:{org_id}"
    now = time.time()

    # Clean old entries
    if key in _rate_limits:
        _rate_limits[key] = [ts for ts in _rate_limits[key] if now - ts < RATE_LIMIT_WINDOW]
    else:
        _rate_limits[key] = []

    if len(_rate_limits[key]) >= RATE_LIMIT_MAX:
        return True

    _rate_limits[key].append(now)
    return False


# ============================================================================
# LAST RUN STORAGE — In-memory (production: use Redis/DB)
# ============================================================================

_last_runs: Dict[str, Dict[str, Any]] = {}


def _store_last_run(org_id: str, agent: str, result: dict):
    """Store last run result for an org/agent."""
    key = f"{org_id}:{agent}"
    _last_runs[key] = {
        **result,
        "stored_at": datetime.utcnow().isoformat(),
    }


def _get_last_run(org_id: str, agent: str) -> Optional[dict]:
    """Get last run result for an org/agent."""
    key = f"{org_id}:{agent}"
    return _last_runs.get(key)


# ============================================================================
# REQUEST MODELS
# ============================================================================

class DiagnosticRunRequest(BaseModel):
    """Request to run a diagnostic agent."""
    agent: Literal["health", "performance", "security", "bug_detection"]
    confirm: str  # Must match exact confirmation phrase


class DiagnosticStatusResponse(BaseModel):
    """Response for GET /status."""
    request_id: str
    agents: list
    last_runs: dict
    timestamp: str


class DiagnosticRunResponse(BaseModel):
    """Response for POST /run."""
    request_id: str
    ok: bool
    agent: str
    started_at: str
    completed_at: str
    results_summary: str
    findings: list
    severity_counts: dict


# ============================================================================
# RBAC HELPERS
# ============================================================================

def _require_view_access(ctx: AuthContext):
    """Require at least view access (any authenticated user)."""
    if not ctx["user_id"]:
        raise HTTPException(status_code=401, detail="Authentication required")


def _require_admin_access(ctx: AuthContext):
    """Require admin/manage_roles access for running diagnostics."""
    if not ctx["user_id"]:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Check Clerk metadata
    clerk_metadata = ctx.get("clerk_metadata") or {}
    clerk_role = clerk_metadata.get("role", "")
    if clerk_role in ["admin", "org:admin", "owner"]:
        return

    # Check database role
    permissions = ctx.get("permissions")
    if permissions:
        db_role = permissions.get("role", "")
        if db_role in ["admin", "owner"]:
            return

    raise HTTPException(
        status_code=403,
        detail="Admin permission required to run diagnostics."
    )


def _generate_request_id() -> str:
    """Generate a unique request ID for tracing."""
    return str(uuid.uuid4())


# ============================================================================
# DIAGNOSTIC AGENTS — Bounded checks with timeouts
# ============================================================================

async def _run_health_checks() -> tuple[list, dict, str]:
    """Run health diagnostic checks. Returns (findings, severity_counts, summary)."""
    findings = []
    severity_counts = {"info": 0, "warning": 0, "critical": 0, "error": 0}

    # Check backend health (timeout 5s)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Self-health check
            backend_url = os.getenv("BACKEND_URL", "http://localhost:8000")
            try:
                resp = await client.get(f"{backend_url}/health")
                if resp.status_code != 200:
                    findings.append({
                        "component": "Backend",
                        "severity": "warning",
                        "message": f"Backend health check returned {resp.status_code}",
                    })
                    severity_counts["warning"] += 1
            except Exception as e:
                findings.append({
                    "component": "Backend",
                    "severity": "error",
                    "message": f"Cannot reach backend: {str(e)[:100]}",
                })
                severity_counts["error"] += 1

            # Database connectivity (via health endpoint data)
            try:
                resp = await client.get(f"{backend_url}/health")
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("database") != "ok":
                        findings.append({
                            "component": "Database",
                            "severity": "warning",
                            "message": "Database connection may be degraded",
                        })
                        severity_counts["warning"] += 1
            except Exception:
                pass

    except Exception as e:
        findings.append({
            "component": "Health Check",
            "severity": "error",
            "message": f"Health check failed: {str(e)[:100]}",
        })
        severity_counts["error"] += 1

    total = sum(severity_counts.values())
    summary = f"Checked {total} components. " + ", ".join(
        f"{count} {sev}" for sev, count in severity_counts.items() if count > 0
    ) if total > 0 else "No issues found."

    return findings, severity_counts, summary


async def _run_performance_checks() -> tuple[list, dict, str]:
    """Run performance diagnostic checks."""
    findings = []
    severity_counts = {"info": 0, "warning": 0, "critical": 0, "error": 0}

    # Check memory (if psutil available)
    try:
        import psutil
        memory = psutil.virtual_memory()
        if memory.percent > 85:
            findings.append({
                "component": "Memory",
                "severity": "critical",
                "message": f"High memory usage: {memory.percent}%",
            })
            severity_counts["critical"] += 1
        elif memory.percent > 70:
            findings.append({
                "component": "Memory",
                "severity": "warning",
                "message": f"Elevated memory usage: {memory.percent}%",
            })
            severity_counts["warning"] += 1
        else:
            findings.append({
                "component": "Memory",
                "severity": "info",
                "message": f"Memory usage normal: {memory.percent}%",
            })
            severity_counts["info"] += 1
    except ImportError:
        findings.append({
            "component": "Memory",
            "severity": "info",
            "message": "psutil not available for memory check",
        })
        severity_counts["info"] += 1

    total = sum(severity_counts.values())
    summary = f"Checked {total} metrics. " + ", ".join(
        f"{count} {sev}" for sev, count in severity_counts.items() if count > 0
    ) if total > 0 else "No issues found."

    return findings, severity_counts, summary


async def _run_security_checks() -> tuple[list, dict, str]:
    """Run security diagnostic checks."""
    findings = []
    severity_counts = {"info": 0, "warning": 0, "critical": 0, "error": 0}

    # Check CORS configuration
    cors_origins = os.getenv("CORS_ORIGINS", "")
    if "*" in cors_origins:
        findings.append({
            "component": "CORS",
            "severity": "critical",
            "message": "CORS allows all origins (*) - security risk",
        })
        severity_counts["critical"] += 1
    else:
        findings.append({
            "component": "CORS",
            "severity": "info",
            "message": "CORS properly configured",
        })
        severity_counts["info"] += 1

    # Check debug mode in production
    if os.getenv("ENVIRONMENT", "development") == "production":
        if os.getenv("DEBUG", "false").lower() == "true":
            findings.append({
                "component": "Debug Mode",
                "severity": "critical",
                "message": "Debug mode enabled in production",
            })
            severity_counts["critical"] += 1

    # Check for required security env vars (redacted)
    required_vars = ["JWT_SECRET", "CLERK_SECRET_KEY"]
    for var in required_vars:
        if not os.getenv(var):
            findings.append({
                "component": "Configuration",
                "severity": "warning",
                "message": f"Security variable {var} not set",
            })
            severity_counts["warning"] += 1

    total = sum(severity_counts.values())
    summary = f"Checked {total} security items. " + ", ".join(
        f"{count} {sev}" for sev, count in severity_counts.items() if count > 0
    ) if total > 0 else "No issues found."

    return findings, severity_counts, summary


async def _run_bug_detection_checks() -> tuple[list, dict, str]:
    """Run bug detection diagnostic checks."""
    findings = []
    severity_counts = {"info": 0, "warning": 0, "critical": 0, "error": 0}

    # Check Sentry configuration
    sentry_dsn = os.getenv("SENTRY_DSN")
    if not sentry_dsn:
        findings.append({
            "component": "Error Tracking",
            "severity": "warning",
            "message": "Sentry not configured - errors may go untracked",
        })
        severity_counts["warning"] += 1
    else:
        findings.append({
            "component": "Error Tracking",
            "severity": "info",
            "message": "Sentry configured for error tracking",
        })
        severity_counts["info"] += 1

    # Check logging configuration
    log_level = os.getenv("LOG_LEVEL", "INFO")
    if log_level.upper() == "DEBUG":
        findings.append({
            "component": "Logging",
            "severity": "info",
            "message": "Debug logging enabled (may impact performance)",
        })
        severity_counts["info"] += 1

    total = sum(severity_counts.values())
    summary = f"Checked {total} bug detection items. " + ", ".join(
        f"{count} {sev}" for sev, count in severity_counts.items() if count > 0
    ) if total > 0 else "No issues found."

    return findings, severity_counts, summary


# ============================================================================
# ENDPOINTS
# ============================================================================

@router.get("/status")
async def get_diagnostics_status(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    GET /api/diagnostics/status

    Returns available diagnostic agents and last_run metadata.

    Auth: get_current_context
    RBAC: view access (any authenticated user)
    """
    _require_view_access(ctx)

    request_id = _generate_request_id()
    org_id = ctx.org_id or "default"

    agents = [
        {
            "id": "health",
            "name": "Health Agent",
            "description": "System health analysis",
            "confirmation_phrase": CONFIRMATION_PHRASES["health"],
        },
        {
            "id": "performance",
            "name": "Performance Agent",
            "description": "Response times & resource usage",
            "confirmation_phrase": CONFIRMATION_PHRASES["performance"],
        },
        {
            "id": "security",
            "name": "Security Agent",
            "description": "Auth & vulnerability checks",
            "confirmation_phrase": CONFIRMATION_PHRASES["security"],
        },
        {
            "id": "bug_detection",
            "name": "Bug Detection Agent",
            "description": "Error tracking & exception analysis",
            "confirmation_phrase": CONFIRMATION_PHRASES["bug_detection"],
        },
    ]

    # Get last run info for each agent
    last_runs = {}
    for agent in agents:
        last_run = _get_last_run(org_id, agent["id"])
        if last_run:
            last_runs[agent["id"]] = {
                "completed_at": last_run.get("completed_at"),
                "ok": last_run.get("ok"),
                "summary": last_run.get("results_summary"),
            }

    return {
        "request_id": request_id,
        "agents": agents,
        "last_runs": last_runs,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.post("/run")
async def run_diagnostic(
    request: DiagnosticRunRequest,
    ctx: AuthContext = Depends(get_current_context),
):
    """
    POST /api/diagnostics/run

    Run a diagnostic agent. Requires exact confirmation phrase.

    Auth: get_current_context
    RBAC: manage_roles (ADMIN-only)
    Rate limit: 5/min/org

    Body:
        agent: "health" | "performance" | "security" | "bug_detection"
        confirm: Exact phrase (e.g., "RUN HEALTH AGENT")
    """
    _require_admin_access(ctx)

    request_id = _generate_request_id()
    org_id = ctx.org_id or "default"

    # Rate limit check
    if _check_rate_limit(org_id):
        raise HTTPException(
            status_code=429,
            detail={
                "error": "Rate limit exceeded",
                "message": f"Maximum {RATE_LIMIT_MAX} diagnostic runs per minute per organization",
                "request_id": request_id,
            }
        )

    # Confirmation phrase check (FAIL CLOSED)
    expected_phrase = CONFIRMATION_PHRASES.get(request.agent)
    if not expected_phrase:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Invalid agent",
                "message": f"Unknown agent: {request.agent}",
                "request_id": request_id,
            }
        )

    if request.confirm != expected_phrase:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "Confirmation phrase mismatch",
                "message": f"Expected exact phrase: '{expected_phrase}'",
                "request_id": request_id,
            }
        )

    # Run the appropriate diagnostic
    started_at = datetime.utcnow()

    try:
        if request.agent == "health":
            findings, severity_counts, summary = await _run_health_checks()
        elif request.agent == "performance":
            findings, severity_counts, summary = await _run_performance_checks()
        elif request.agent == "security":
            findings, severity_counts, summary = await _run_security_checks()
        elif request.agent == "bug_detection":
            findings, severity_counts, summary = await _run_bug_detection_checks()
        else:
            raise ValueError(f"Unknown agent: {request.agent}")

        ok = severity_counts.get("critical", 0) == 0 and severity_counts.get("error", 0) == 0

    except Exception as e:
        findings = [{
            "component": "Diagnostic",
            "severity": "error",
            "message": f"Diagnostic failed: {str(e)[:200]}",
        }]
        severity_counts = {"error": 1}
        summary = "Diagnostic execution failed"
        ok = False

    completed_at = datetime.utcnow()

    result = {
        "request_id": request_id,
        "ok": ok,
        "agent": request.agent,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "results_summary": summary,
        "findings": findings,
        "severity_counts": severity_counts,
    }

    # Store last run
    _store_last_run(org_id, request.agent, result)

    return result


@router.get("/last")
async def get_last_diagnostic(
    agent: Literal["health", "performance", "security", "bug_detection"],
    ctx: AuthContext = Depends(get_current_context),
):
    """
    GET /api/diagnostics/last?agent=...

    Get last diagnostic result for an agent (read-only).

    Auth: get_current_context
    RBAC: view access
    """
    _require_view_access(ctx)

    request_id = _generate_request_id()
    org_id = ctx.org_id or "default"

    last_run = _get_last_run(org_id, agent)

    if not last_run:
        return {
            "request_id": request_id,
            "agent": agent,
            "last_run": None,
            "message": "No previous run found for this agent",
        }

    return {
        "request_id": request_id,
        "agent": agent,
        "last_run": last_run,
    }
