# app/middleware/canonical_guard.py
"""
ReconAI Canonical Guard - Enforcement Module

Implements the five Canonical Laws:
1. Advisory-only behavior - NO autonomous actions
2. Manual-run only - Requires explicit human trigger
3. Read-only execution - No write operations without approval
4. Confidence gating >= 0.85 - All decisions must meet threshold
5. Mandatory evidence attachment - All operations must have evidence

RULES:
- No autonomous execution
- No speculative changes
- Trust > Speed
- Security > Convenience
"""

from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import uuid


# =============================================================================
# CANONICAL LAWS CONFIGURATION (IMMUTABLE)
# =============================================================================

class CanonicalLaws:
    """Immutable canonical laws configuration"""
    ADVISORY_ONLY = True
    MANUAL_RUN_ONLY = True
    READ_ONLY_MODE = True
    CONFIDENCE_THRESHOLD = 0.85
    EVIDENCE_REQUIRED = True

    # SECURITY: These values cannot be changed at runtime
    @classmethod
    def get_all(cls) -> Dict[str, Any]:
        return {
            "advisory_only": cls.ADVISORY_ONLY,
            "manual_run_only": cls.MANUAL_RUN_ONLY,
            "read_only_mode": cls.READ_ONLY_MODE,
            "confidence_threshold": cls.CONFIDENCE_THRESHOLD,
            "evidence_required": cls.EVIDENCE_REQUIRED
        }


class ExecutionMode(Enum):
    """Allowed execution modes"""
    ADVISORY = "advisory"
    BLOCKED = "blocked"


class TriggerType(Enum):
    """Valid human trigger types"""
    USER_CLICK = "user_click"
    USER_COMMAND = "user_command"
    EXPLICIT_APPROVAL = "explicit_approval"
    MANUAL_CONFIRMATION = "manual_confirmation"
    HUMAN_INITIATED = "human_initiated"


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class Evidence:
    """Evidence attachment for operations"""
    source: str
    timestamp: str
    data: Dict[str, Any]
    hash: str
    retention_policy: str = "permanent"
    canonical_compliant: bool = True


@dataclass
class CanonicalGuardResult:
    """Result of canonical guard enforcement"""
    allowed: bool
    mode: ExecutionMode
    checks: Dict[str, bool]
    advisory_message: str
    evidence: Optional[Evidence] = None
    audited_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class HumanTrigger:
    """Human trigger context"""
    trigger_type: TriggerType
    triggered_by: str
    triggered_at: datetime
    metadata: Optional[Dict[str, Any]] = None


# =============================================================================
# GUARD STATE (IMMUTABLE)
# =============================================================================

# SECURITY: Guard is ALWAYS enabled - this cannot be changed
_GUARD_ENABLED = True

# Audit trail storage (append-only)
_audit_trail: List[Dict[str, Any]] = []


# =============================================================================
# WRITE OPERATION DETECTION
# =============================================================================

WRITE_OPERATIONS = frozenset([
    "write", "update", "delete", "create", "modify",
    "insert", "remove", "execute", "deploy", "push",
    "post", "put", "patch"
])


def is_read_only_safe(operation: Dict[str, Any]) -> Dict[str, Any]:
    """
    Check if an operation is read-only safe.

    Args:
        operation: Operation details including type and action

    Returns:
        Dict with 'safe' boolean and 'reason' string
    """
    op_type = str(operation.get("type", "")).lower()
    op_action = str(operation.get("action", "")).lower()
    method = str(operation.get("method", "")).lower()

    # Check against write operations
    for write_op in WRITE_OPERATIONS:
        if write_op in op_type or write_op in op_action or write_op == method:
            return {
                "safe": False,
                "reason": f"Write operation detected: {write_op}",
                "detected_in": op_type or op_action or method
            }

    return {
        "safe": True,
        "reason": "Operation is read-only safe"
    }


# =============================================================================
# EVIDENCE FUNCTIONS
# =============================================================================

def generate_evidence_hash(data: Dict[str, Any]) -> str:
    """Generate a hash for evidence data"""
    json_str = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(json_str.encode()).hexdigest()[:16]


def create_evidence(source: str, data: Dict[str, Any]) -> Evidence:
    """
    Create an evidence attachment.

    Args:
        source: Source of the evidence (e.g., 'canonical-guard', 'api-call')
        data: Evidence data

    Returns:
        Evidence object with hash
    """
    timestamp = datetime.now().isoformat()
    evidence_data = {
        "source": source,
        "timestamp": timestamp,
        "data": data
    }

    return Evidence(
        source=source,
        timestamp=timestamp,
        data=data,
        hash=generate_evidence_hash(evidence_data),
        retention_policy="permanent",
        canonical_compliant=True
    )


def validate_evidence(evidence: Optional[Evidence]) -> Dict[str, Any]:
    """
    Validate that evidence meets canonical requirements.

    Args:
        evidence: Evidence to validate

    Returns:
        Dict with 'valid' boolean and validation details
    """
    if not CanonicalLaws.EVIDENCE_REQUIRED:
        return {"valid": True, "reason": "Evidence not required"}

    if not evidence:
        return {
            "valid": False,
            "reason": "Evidence is required but not provided"
        }

    required_fields = ["source", "timestamp", "data", "hash"]
    missing = [f for f in required_fields if not getattr(evidence, f, None)]

    if missing:
        return {
            "valid": False,
            "reason": f"Missing required fields: {', '.join(missing)}"
        }

    return {
        "valid": True,
        "reason": "Evidence is complete and valid",
        "evidence_hash": evidence.hash
    }


# =============================================================================
# HUMAN TRIGGER VALIDATION
# =============================================================================

def validate_human_trigger(trigger: Optional[HumanTrigger]) -> Dict[str, Any]:
    """
    Validate that a human trigger is present and valid.

    Args:
        trigger: Human trigger to validate

    Returns:
        Dict with 'valid' boolean and validation details
    """
    if not CanonicalLaws.MANUAL_RUN_ONLY:
        return {"valid": True, "reason": "Manual run not required"}

    if not trigger:
        return {
            "valid": False,
            "reason": "Human trigger is required but not provided"
        }

    if not trigger.triggered_by:
        return {
            "valid": False,
            "reason": "Trigger must identify who triggered the operation"
        }

    if not isinstance(trigger.trigger_type, TriggerType):
        return {
            "valid": False,
            "reason": f"Invalid trigger type: {trigger.trigger_type}"
        }

    return {
        "valid": True,
        "reason": "Human trigger is valid",
        "trigger_type": trigger.trigger_type.value,
        "triggered_by": trigger.triggered_by
    }


# =============================================================================
# CONFIDENCE VALIDATION
# =============================================================================

def validate_confidence(confidence: float) -> Dict[str, Any]:
    """
    Validate that confidence meets the canonical threshold.

    Args:
        confidence: Confidence score (0-1)

    Returns:
        Dict with 'valid' boolean and validation details
    """
    threshold = CanonicalLaws.CONFIDENCE_THRESHOLD

    if not isinstance(confidence, (int, float)):
        return {
            "valid": False,
            "reason": "Confidence must be a number",
            "threshold": threshold
        }

    if confidence < 0 or confidence > 1:
        return {
            "valid": False,
            "reason": "Confidence must be between 0 and 1",
            "provided": confidence,
            "threshold": threshold
        }

    passed = confidence >= threshold

    return {
        "valid": passed,
        "reason": f"Confidence {'meets' if passed else 'below'} threshold",
        "provided": confidence,
        "threshold": threshold,
        "delta": confidence - threshold
    }


# =============================================================================
# ADVISORY RESPONSE
# =============================================================================

def create_advisory_response(
    operation: Dict[str, Any],
    recommendation: str,
    confidence: float,
    evidence: Optional[Evidence] = None
) -> Dict[str, Any]:
    """
    Create an advisory-only response (no autonomous execution).

    Args:
        operation: The operation being advised on
        recommendation: The recommended action
        confidence: Confidence in the recommendation
        evidence: Supporting evidence

    Returns:
        Advisory response dict
    """
    return {
        "type": "advisory",
        "autonomous": False,
        "execution_allowed": False,
        "recommendation": recommendation,
        "confidence": confidence,
        "human_action_required": {
            "required": True,
            "message": "Human approval required to proceed",
            "actions": ["approve", "reject", "modify"]
        },
        "operation_id": operation.get("id", str(uuid.uuid4())),
        "evidence": evidence.__dict__ if evidence else None,
        "created_at": datetime.now().isoformat()
    }


# =============================================================================
# MAIN ENFORCEMENT FUNCTION
# =============================================================================

def enforce_canonical_guard(
    operation: Dict[str, Any],
    confidence: float,
    evidence: Optional[Evidence] = None,
    trigger: Optional[HumanTrigger] = None
) -> CanonicalGuardResult:
    """
    Main canonical guard enforcement function.

    Validates all five canonical laws:
    1. Advisory-only behavior
    2. Manual-run only
    3. Read-only execution
    4. Confidence gating >= 0.85
    5. Mandatory evidence attachment

    Args:
        operation: Operation details
        confidence: Confidence score (0-1)
        evidence: Evidence attachment
        trigger: Human trigger context

    Returns:
        CanonicalGuardResult with enforcement decision
    """
    if not _GUARD_ENABLED:
        # This should never happen - guard is always enabled
        raise RuntimeError("SECURITY VIOLATION: Canonical guard cannot be disabled")

    checks = {
        "advisory_only": True,  # Always advisory
        "manual_run": False,
        "read_only": False,
        "confidence": False,
        "evidence": False
    }

    messages = []

    # Check 1: Advisory-only (always passes - we're always advisory)
    checks["advisory_only"] = CanonicalLaws.ADVISORY_ONLY

    # Check 2: Manual-run only (human trigger required)
    trigger_result = validate_human_trigger(trigger)
    checks["manual_run"] = trigger_result["valid"]
    if not trigger_result["valid"]:
        messages.append(f"Manual trigger: {trigger_result['reason']}")

    # Check 3: Read-only mode
    read_only_result = is_read_only_safe(operation)
    checks["read_only"] = read_only_result["safe"]
    if not read_only_result["safe"]:
        messages.append(f"Read-only: {read_only_result['reason']}")

    # Check 4: Confidence threshold
    confidence_result = validate_confidence(confidence)
    checks["confidence"] = confidence_result["valid"]
    if not confidence_result["valid"]:
        messages.append(f"Confidence: {confidence_result['reason']} ({confidence:.2f} < {CanonicalLaws.CONFIDENCE_THRESHOLD})")

    # Check 5: Evidence required
    evidence_result = validate_evidence(evidence)
    checks["evidence"] = evidence_result["valid"]
    if not evidence_result["valid"]:
        messages.append(f"Evidence: {evidence_result['reason']}")

    # Determine if operation is allowed
    all_passed = all(checks.values())

    # Create result
    result = CanonicalGuardResult(
        allowed=all_passed,
        mode=ExecutionMode.ADVISORY if all_passed else ExecutionMode.BLOCKED,
        checks=checks,
        advisory_message="; ".join(messages) if messages else "All canonical checks passed",
        evidence=evidence
    )

    # Append to audit trail (append-only)
    _audit_trail.append({
        "operation_id": operation.get("id", "unknown"),
        "operation_type": operation.get("type", "unknown"),
        "result": result.allowed,
        "checks": checks,
        "messages": messages,
        "audited_at": result.audited_at
    })

    return result


# =============================================================================
# AUDIT TRAIL FUNCTIONS
# =============================================================================

def get_audit_trail() -> List[Dict[str, Any]]:
    """
    Get the canonical guard audit trail.

    Note: Audit trail is append-only and cannot be cleared.

    Returns:
        List of audit entries
    """
    return list(_audit_trail)


def get_canonical_laws() -> Dict[str, Any]:
    """Get current canonical laws configuration"""
    return CanonicalLaws.get_all()


# =============================================================================
# FASTAPI MIDDLEWARE INTEGRATION
# =============================================================================

from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware


class CanonicalGuardMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware for canonical guard enforcement.

    Enforces read-only mode for non-GET requests without approval.
    """

    # Paths that bypass the guard (health checks, etc.)
    BYPASS_PATHS = frozenset(["/", "/health", "/docs", "/openapi.json", "/redoc"])

    # Methods that are read-only safe
    SAFE_METHODS = frozenset(["GET", "HEAD", "OPTIONS"])

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method

        # Bypass for health checks and docs
        if path in self.BYPASS_PATHS:
            return await call_next(request)

        # Safe methods pass through with logging
        if method in self.SAFE_METHODS:
            return await call_next(request)

        # For write operations, check for approval header
        approval_header = request.headers.get("X-Canonical-Approval")
        confidence_header = request.headers.get("X-Canonical-Confidence", "0")

        try:
            confidence = float(confidence_header)
        except ValueError:
            confidence = 0.0

        # Create operation context
        operation = {
            "id": str(uuid.uuid4()),
            "type": "api_request",
            "action": method.lower(),
            "method": method,
            "path": path
        }

        # Create trigger if approval header present
        trigger = None
        if approval_header:
            trigger = HumanTrigger(
                trigger_type=TriggerType.EXPLICIT_APPROVAL,
                triggered_by=approval_header,
                triggered_at=datetime.now()
            )

        # Create evidence
        evidence = create_evidence("api-middleware", {
            "method": method,
            "path": path,
            "has_approval": bool(approval_header)
        })

        # Enforce canonical guard
        result = enforce_canonical_guard(
            operation=operation,
            confidence=confidence,
            evidence=evidence,
            trigger=trigger
        )

        if not result.allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "Canonical guard blocked operation",
                    "message": result.advisory_message,
                    "checks": result.checks,
                    "mode": result.mode.value
                }
            )

        return await call_next(request)
