# ReconAI Backend Failure Modes

**Version:** 1.0.0
**Last Updated:** 2026-01-26
**Status:** PRODUCTION READY

---

## Overview

This document enumerates all known backend failure scenarios, their symptoms, user impact, and recovery procedures.

**Guiding Principle:** FAIL CLOSED. When in doubt, reject the request with a clear error rather than producing incorrect results.

---

## 1. Database Unavailable

### Symptoms
- Health check returns `"database": "error: ..."`
- All API requests return 500 errors
- Sentry alerts with `sqlite3.OperationalError`

### User-Visible Response
```json
{
  "error": {
    "code": "INTERNAL_ERROR",
    "message": "Internal server error",
    "request_id": "abc123"
  }
}
```

### HTTP Status
`500 Internal Server Error`

### Operator Log Signals
```
ERROR database connection failed
ERROR sqlite3.OperationalError: unable to open database file
```

### Immediate Mitigation
1. Check Render dashboard for disk issues
2. Verify `/var/data` mount is accessible
3. Check disk space: `df -h /var/data`

### Data Integrity Guarantees
- **Audit log:** No writes attempted during failure
- **Transactions:** Rolled back automatically
- **Evidence chain:** Intact (append-only table)

### Recovery Steps
1. Resolve disk/mount issue
2. Restart service via Render dashboard
3. Verify health check passes
4. Check audit log for gaps

---

## 2. Database Latency Spike

### Symptoms
- Request latency p99 > 5s
- Timeouts on complex queries
- Health check slow but passes

### User-Visible Response
```json
{
  "error": {
    "code": "TIMEOUT",
    "message": "Request timed out",
    "request_id": "abc123"
  }
}
```

### HTTP Status
`504 Gateway Timeout` or `500 Internal Server Error`

### Operator Log Signals
```
WARN query took 5000ms: SELECT * FROM core_transactions...
ERROR request timeout after 30000ms
```

### Immediate Mitigation
1. Check for long-running queries
2. Enable incident mode if widespread
3. Identify problematic endpoint

### Data Integrity Guarantees
- **Writes:** Transactions ensure atomicity
- **Reads:** May return stale data if timeout during read

### Recovery Steps
1. Identify slow query via logs
2. Add missing index if needed
3. Optimize query or add pagination
4. Monitor latency after fix

---

## 3. Partial API Outage

### Symptoms
- Some endpoints return errors
- Other endpoints work normally
- Sentry shows errors for specific routes

### User-Visible Response
```json
{
  "error": {
    "code": "SERVICE_ERROR",
    "message": "Service temporarily unavailable",
    "request_id": "abc123"
  }
}
```

### HTTP Status
`503 Service Unavailable` or `500 Internal Server Error`

### Operator Log Signals
```
ERROR ImportError: cannot import module 'app.routers.xxx'
ERROR AttributeError in endpoint handler
```

### Immediate Mitigation
1. Identify affected routes via Sentry
2. If critical, enable incident mode
3. Route traffic away if possible

### Data Integrity Guarantees
- **Working routes:** Unaffected
- **Broken routes:** Fail closed, no partial writes

### Recovery Steps
1. Fix code issue
2. Deploy fix or rollback
3. Verify all routes healthy
4. Disable incident mode

---

## 4. Long-Running Reconciliation/Export

### Symptoms
- Export requests hang > 30s
- Reconciliation runs timeout
- Memory usage spikes

### User-Visible Response
```json
{
  "error": {
    "code": "TIMEOUT",
    "message": "Operation timed out. Please try with smaller date range.",
    "request_id": "abc123"
  }
}
```

### HTTP Status
`504 Gateway Timeout`

### Operator Log Signals
```
WARN reconciliation run exceeding 30s for org_xxx
WARN export generation failed: timeout
```

### Immediate Mitigation
1. These are manual-triggered operations
2. User can retry with smaller scope
3. No automatic retry (by design)

### Data Integrity Guarantees
- **Reconciliation:** Snapshot captured at start, immutable
- **Exports:** All-or-nothing (no partial exports)
- **Audit log:** Attempt logged even on failure

### Recovery Steps
1. User reduces date range or scope
2. If persistent, investigate data volume
3. Consider adding pagination/chunking

---

## 5. Third-Party Failure: Plaid

### Symptoms
- Bank connection operations fail
- Transaction sync errors
- Plaid webhook delivery fails

### User-Visible Response
```json
{
  "error": {
    "code": "PLAID_ERROR",
    "message": "Unable to connect to bank services. Please try again later.",
    "request_id": "abc123",
    "plaid_error_code": "INSTITUTION_DOWN"
  }
}
```

### HTTP Status
`502 Bad Gateway` or `503 Service Unavailable`

### Operator Log Signals
```
ERROR Plaid API error: INSTITUTION_DOWN
ERROR Plaid request timeout after 10000ms
```

### Immediate Mitigation
1. Check https://status.plaid.com
2. Inform users if Plaid-wide outage
3. No automatic retry (user must re-initiate)

### Data Integrity Guarantees
- **Existing data:** Unaffected
- **Pending syncs:** Not started, no partial data
- **Access tokens:** Encrypted, unchanged

### Recovery Steps
1. Wait for Plaid recovery
2. User re-initiates sync
3. Verify transaction count matches

---

## 6. Third-Party Failure: Stripe

### Symptoms
- Payment operations fail
- Checkout session creation errors
- Webhook validation fails

### User-Visible Response
```json
{
  "error": {
    "code": "PAYMENT_ERROR",
    "message": "Payment service temporarily unavailable",
    "request_id": "abc123"
  }
}
```

### HTTP Status
`502 Bad Gateway` or `503 Service Unavailable`

### Operator Log Signals
```
ERROR Stripe API error: Connection refused
ERROR Stripe webhook signature invalid
```

### Immediate Mitigation
1. Check https://status.stripe.com
2. Inform users of payment issues
3. Webhooks will be retried by Stripe

### Data Integrity Guarantees
- **Subscriptions:** Stripe is source of truth
- **Local status:** May lag, resolved on next sync

### Recovery Steps
1. Wait for Stripe recovery
2. Stripe auto-retries webhooks
3. Verify subscription status matches

---

## 7. Third-Party Failure: Clerk

### Symptoms
- All authenticated requests fail
- JWT validation errors
- 401 errors across all protected routes

### User-Visible Response
```json
{
  "error": {
    "code": "AUTH_ERROR",
    "message": "Authentication service unavailable",
    "request_id": "abc123"
  }
}
```

### HTTP Status
`401 Unauthorized` or `503 Service Unavailable`

### Operator Log Signals
```
ERROR Clerk JWT validation failed: connection error
ERROR Unable to fetch Clerk JWKS
```

### Immediate Mitigation
1. Check https://clerk.dev/status
2. Enable incident mode (blocks all anyway)
3. Inform users

### Data Integrity Guarantees
- **User data:** Stored locally, unaffected
- **Operations:** Blocked at auth layer, no writes

### Recovery Steps
1. Wait for Clerk recovery
2. Disable incident mode
3. Users refresh session

---

## 8. Corrupt Export Attempt

### Symptoms
- Export file generation fails
- Hash validation errors
- Evidence chain broken

### User-Visible Response
```json
{
  "error": {
    "code": "EXPORT_FAILED",
    "message": "Export generation failed. Please contact support.",
    "request_id": "abc123"
  }
}
```

### HTTP Status
`500 Internal Server Error`

### Operator Log Signals
```
ERROR Export hash mismatch: expected abc, got def
ERROR Evidence chain validation failed for export_xxx
```

### Immediate Mitigation
1. This indicates data integrity issue
2. Enable incident mode immediately
3. Do NOT retry until investigated

### Data Integrity Guarantees
- **Export:** NOT generated (fail closed)
- **Evidence:** Original chain preserved
- **Audit:** Failure logged for investigation

### Recovery Steps
1. Investigate source of corruption
2. Verify audit chain integrity
3. Regenerate export from verified data
4. Postmortem required

---

## 9. Audit Store Write Failure

### Symptoms
- Audit log insert fails
- Operations blocked by audit requirement
- Evidence chain integrity warnings

### User-Visible Response
```json
{
  "error": {
    "code": "AUDIT_WRITE_FAILED",
    "message": "Unable to record audit event. Operation blocked.",
    "request_id": "abc123"
  }
}
```

### HTTP Status
`503 Service Unavailable`

### Operator Log Signals
```
ERROR Audit event insert failed: database locked
ERROR Hash chain verification failed
CRITICAL Audit store unavailable - blocking all writes
```

### Immediate Mitigation
1. **CRITICAL:** Enable incident mode immediately
2. This is DCAA compliance issue
3. Block all mutating operations

### Data Integrity Guarantees
- **Fail closed:** Operation blocked if audit fails
- **Chain:** No gaps allowed
- **Compliance:** Maintained by failing closed

### Recovery Steps
1. Fix database issue
2. Verify chain integrity: `GET /api/audit/verify`
3. If chain broken, reconstruct from backups
4. Document incident for DCAA

---

## 10. Memory Exhaustion

### Symptoms
- Service becomes unresponsive
- OOM killer terminates process
- Render auto-restarts service

### User-Visible Response
Connection refused or timeout (no JSON response)

### HTTP Status
No response (connection refused)

### Operator Log Signals
```
Render: Service restarted due to memory limit
ERROR MemoryError: unable to allocate ...
```

### Immediate Mitigation
1. Render auto-restarts service
2. Identify memory-intensive operation
3. Add memory limits to queries

### Data Integrity Guarantees
- **Transactions:** Rolled back on crash
- **Audit log:** Last committed entry preserved
- **Pending writes:** Lost (must be retried)

### Recovery Steps
1. Service auto-recovers via restart
2. Identify leak via memory profiling
3. Fix or add memory bounds
4. Consider upgrading Render plan

---

## Summary: Failure Response Matrix

| Scenario | HTTP | User Message | Operator Action | Data Safe? |
|----------|------|--------------|-----------------|------------|
| DB Unavailable | 500 | Internal error | Check disk/mount | Yes |
| DB Latency | 504 | Timeout | Add index | Yes |
| Partial Outage | 503 | Service error | Fix code | Yes |
| Long Export | 504 | Timeout | Reduce scope | Yes |
| Plaid Down | 502 | Bank unavailable | Wait | Yes |
| Stripe Down | 502 | Payment unavailable | Wait | Yes |
| Clerk Down | 401 | Auth unavailable | Wait | Yes |
| Corrupt Export | 500 | Contact support | Investigate | Yes (blocked) |
| Audit Failure | 503 | Operation blocked | Incident mode | Yes (blocked) |
| Memory OOM | - | Connection refused | Auto-restart | Partial |
