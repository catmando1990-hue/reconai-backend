# ReconAI Backend Adversarial Validation Report

**Version:** Phase 3.5
**Date:** 2026-01-26
**Status:** FAILURES FOUND - FIXES REQUIRED

---

## Executive Summary

Adversarial testing of the ReconAI backend revealed **5 critical findings** that violate core system invariants. Multi-tenant isolation is fundamentally broken in GovCon modules. Incident mode is fail-open, not fail-closed.

**Verdict: SYSTEM IS NOT PRODUCTION-READY until P0/P1 issues are resolved.**

---

## Findings

### FINDING #1: GovCon Multi-Tenant Isolation BROKEN

| Attribute | Value |
|-----------|-------|
| **Invariant Tested** | Org isolation |
| **Attack Vector** | Cross-org ID guessing on GovCon endpoints |
| **Expected Behavior** | HTTP 403/404, no data leakage, audit log of attempt |
| **Actual Behavior** | ANY authenticated user with GovCon entitlement can access ANY timesheet/contract/pool/report by ID |
| **Severity** | **P0 - CRITICAL** |
| **Fix Required** | **REQUIRED** |

**Technical Details:**

1. GovCon models (`Timesheet`, `Contract`, `IndirectPool`, `ReconciliationReport`) have **NO `org_id` field**
2. Data lookups use only entity ID without org scope:
   ```python
   # govcon_timekeeping.py:290-293
   if timesheet_id not in _timesheets:
       raise HTTPException(status_code=404, detail="Timesheet not found")
   timesheet = _timesheets[timesheet_id]  # NO org check!
   ```
3. Router-level auth (`require_govcon_access`) provides authentication but NOT authorization per-resource

**Files Affected:**
- [govcon_timekeeping.py:130-155](app/routers/govcon_timekeeping.py#L130) - Timesheet model, no org_id
- [govcon_contracts.py:101-138](app/routers/govcon_contracts.py#L101) - Contract model, no org_id
- [govcon_indirects.py:117-145](app/routers/govcon_indirects.py#L117) - IndirectPool model, no org_id
- [govcon_reconciliation.py:109-165](app/routers/govcon_reconciliation.py#L109) - ReconciliationReport model, no org_id

**Impact:** Complete cross-tenant data exposure. User from Org A can read/modify Org B's government contracts, timesheets, and reconciliation reports.

---

### FINDING #2: `submit_timesheet` Missing Evidence Requirement

| Attribute | Value |
|-----------|-------|
| **Invariant Tested** | Evidence requirement |
| **Attack Vector** | Submit timesheet without evidence |
| **Expected Behavior** | Mutation blocked, evidence required per canonical law |
| **Actual Behavior** | Submission succeeds with NO evidence |
| **Severity** | **P1 - HIGH** |
| **Fix Required** | **REQUIRED** |

**Technical Details:**

```python
# govcon_timekeeping.py:460-465
@router.post("/timesheets/{timesheet_id}/submit", response_model=dict)
async def submit_timesheet(
    request: Request,
    timesheet_id: str,
    ctx: AuthContext = Depends(require_govcon_access)
):  # <-- NO evidence parameter!
```

**Files Affected:**
- [govcon_timekeeping.py:460-527](app/routers/govcon_timekeeping.py#L460)

**Impact:** Timesheet status can be changed from DRAFT to SUBMITTED without audit evidence, violating DCAA compliance requirements.

---

### FINDING #3: `approve_timesheet` Empty Evidence Accepted

| Attribute | Value |
|-----------|-------|
| **Invariant Tested** | Evidence requirement |
| **Attack Vector** | Approve timesheet with `approval_evidence={}` |
| **Expected Behavior** | Empty evidence rejected |
| **Actual Behavior** | Empty dict `{}` accepted as valid evidence |
| **Severity** | **P1 - HIGH** |
| **Fix Required** | **REQUIRED** |

**Technical Details:**

```python
# govcon_timekeeping.py:529-535
async def approve_timesheet(
    ...
    approval_evidence: dict,  # Required but NOT validated for content
    ...
):
    ...
    timesheet.evidence = approval_evidence  # Line 564 - stored without validation
```

No validation that `approval_evidence` contains meaningful data.

**Files Affected:**
- [govcon_timekeeping.py:529-590](app/routers/govcon_timekeeping.py#L529)

**Impact:** Approvals can be made without substantive evidence, undermining audit trail integrity.

---

### FINDING #4: `calculate_pool_rate` No Auth Context

| Attribute | Value |
|-----------|-------|
| **Invariant Tested** | Audit logging completeness |
| **Attack Vector** | Calculate indirect rate with system user |
| **Expected Behavior** | All mutations logged with actual user_id |
| **Actual Behavior** | Defaults to `user_id: str = "system"` |
| **Severity** | **P2 - MEDIUM** |
| **Fix Required** | **REQUIRED** |

**Technical Details:**

```python
# govcon_indirects.py:442-445
@router.post("/pools/{pool_id}/calculate-rate", response_model=dict)
async def calculate_pool_rate(
    pool_id: str,
    allocation_base_amount: float,
    user_id: str = "system"  # <-- Should be ctx: AuthContext = Depends(...)
):
```

**Files Affected:**
- [govcon_indirects.py:441-495](app/routers/govcon_indirects.py#L441)

**Impact:** Rate calculations logged with "system" user instead of actual user, breaking audit attribution.

---

### FINDING #5: Incident Mode is FAIL-OPEN

| Attribute | Value |
|-----------|-------|
| **Invariant Tested** | Fail-closed behavior |
| **Attack Vector** | Database failure during incident check |
| **Expected Behavior** | Requests blocked when state cannot be verified |
| **Actual Behavior** | Requests ALLOWED when DB query fails |
| **Severity** | **P1 - HIGH** |
| **Fix Required** | **REQUIRED** |

**Technical Details:**

```python
# middleware/incident_guard.py:52-54
try:
    incident_mode = self._check_incident_mode()
except Exception:
    # If we can't check, allow request through  <-- FAIL OPEN!
    return await call_next(request)

# middleware/incident_guard.py:80-81
except sqlite3.Error:
    return False  # <-- Returns "not in incident mode" on error
```

**Files Affected:**
- [middleware/incident_guard.py:39-81](app/middleware/incident_guard.py#L39)

**Impact:** If database is unavailable during an incident, the incident guard is bypassed and all requests are allowed through, defeating the purpose of incident mode.

---

## Invariants Status Summary

| Invariant | Status | Finding |
|-----------|--------|---------|
| Audit immutability | ✅ PASS | Append-only with hash chaining |
| Evidence requirement | ❌ FAIL | #2, #3 |
| Org isolation | ❌ **CRITICAL FAIL** | #1 |
| Math consistency | ✅ PASS | Division by zero protected |
| Snapshot immutability | ✅ PASS | SHA-256 hash, deep copy |
| Fail-closed behavior | ❌ FAIL | #5 |
| Manual-only execution | ✅ PASS | Advisory blocks present |
| Idempotency | ✅ PASS | IdempotencyGuardMiddleware active |

---

## Remediation Priority

| Priority | Finding | Action Required |
|----------|---------|-----------------|
| **P0** | #1 - Multi-tenant isolation | Add `org_id` to all GovCon models, validate on every access |
| **P1** | #2 - submit_timesheet evidence | Add evidence parameter with validation |
| **P1** | #3 - approve_timesheet evidence | Add non-empty evidence validation |
| **P1** | #5 - Incident mode fail-open | Change to fail-closed (block on exception) |
| **P2** | #4 - calculate_pool_rate auth | Replace with AuthContext dependency |

---

## Recommended Fixes

### Fix #1: Multi-Tenant Isolation (P0)

1. Add `org_id: str` field to all GovCon models
2. Store org_id at creation time from auth context
3. Validate `entity.org_id == ctx["org_id"]` on every GET/PUT/DELETE
4. Return 403 on mismatch with audit log

### Fix #2: submit_timesheet Evidence (P1)

```python
async def submit_timesheet(
    request: Request,
    timesheet_id: str,
    submission_evidence: dict,  # ADD THIS
    ctx: AuthContext = Depends(require_govcon_access)
):
    if not submission_evidence or not isinstance(submission_evidence, dict):
        raise HTTPException(status_code=400, detail="Evidence required")
```

### Fix #3: Empty Evidence Validation (P1)

```python
if not approval_evidence or len(approval_evidence) == 0:
    raise HTTPException(status_code=400, detail="Non-empty evidence required")
```

### Fix #4: Auth Context for Rate Calculation (P2)

```python
async def calculate_pool_rate(
    pool_id: str,
    allocation_base_amount: float,
    ctx: AuthContext = Depends(require_govcon_access)  # REPLACE user_id
):
```

### Fix #5: Incident Mode Fail-Closed (P1)

```python
try:
    incident_mode = self._check_incident_mode()
except Exception:
    # FAIL CLOSED: Block request when state is unknown
    return JSONResponse(
        status_code=503,
        content={"error": "STATE_UNKNOWN", "message": "Cannot verify system state"}
    )
```

---

## Conclusion

**SYSTEM STATUS: NOT PRODUCTION-READY**

The multi-tenant isolation failure (Finding #1) is a **showstopper**. GovCon data for government contractors must be strictly isolated per organization. Current implementation allows any GovCon-entitled user to access any organization's data.

**No deployment should proceed until P0 and P1 issues are resolved.**
