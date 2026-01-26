# ReconAI Backend Monitoring & Alerts

**Version:** 1.0.0
**Last Updated:** 2026-01-26
**Status:** PRODUCTION READY

---

## 1. Metrics Definitions

### 1.1 Request Metrics

| Metric | Description | Labels | Type |
|--------|-------------|--------|------|
| `http_requests_total` | Total HTTP requests | method, path, status | Counter |
| `http_request_duration_seconds` | Request latency | method, path | Histogram |
| `http_request_size_bytes` | Request body size | method, path | Histogram |
| `http_response_size_bytes` | Response body size | method, path | Histogram |

**Implementation Note:** Currently tracked via Sentry performance monitoring. For custom metrics, integrate with Prometheus/StatsD.

### 1.2 Error Metrics

| Metric | Description | Labels | Type |
|--------|-------------|--------|------|
| `http_errors_total` | HTTP 4xx/5xx responses | status, error_code | Counter |
| `unhandled_exceptions_total` | Uncaught exceptions | exception_type | Counter |
| `validation_errors_total` | Pydantic validation failures | path | Counter |

**Source:** Sentry error tracking

### 1.3 Business Metrics

| Metric | Description | Labels | Type |
|--------|-------------|--------|------|
| `exports_total` | Export operations | status (success/failure), type | Counter |
| `reconciliation_runs_total` | GovCon reconciliation runs | status, type | Counter |
| `audit_log_writes_total` | Audit event insertions | event_type | Counter |
| `plaid_syncs_total` | Plaid transaction syncs | status | Counter |

### 1.4 Rate Limiting Metrics

| Metric | Description | Labels | Type |
|--------|-------------|--------|------|
| `rate_limit_rejections_total` | Rate limit 429 responses | route_class, reason | Counter |
| `rate_limit_remaining` | Remaining requests in window | route_class | Gauge |

### 1.5 System Metrics

| Metric | Description | Labels | Type |
|--------|-------------|--------|------|
| `incident_mode_active` | Incident mode status | - | Gauge (0/1) |
| `db_connection_errors_total` | Database connection failures | - | Counter |
| `uptime_seconds` | Service uptime | - | Counter |

---

## 2. Alert Thresholds

### 2.1 Critical Alerts (P0 - Immediate)

| Alert | Condition | Duration | Action |
|-------|-----------|----------|--------|
| Service Down | Health check fails | 2 min | Page on-call |
| Database Unavailable | DB health = error | 1 min | Page on-call |
| Error Rate Spike | 5xx rate > 10% | 5 min | Page on-call |
| Incident Mode Active | incident_mode = 1 | Immediate | Notify team |

### 2.2 High Alerts (P1 - < 1 hour)

| Alert | Condition | Duration | Action |
|-------|-----------|----------|--------|
| High Latency | p99 > 5s | 10 min | Slack alert |
| Elevated Error Rate | 5xx rate > 5% | 10 min | Slack alert |
| Rate Limit Storm | 429s > 100/min | 5 min | Slack alert |
| Auth Failures Spike | 401s > 50/min | 5 min | Slack alert |

### 2.3 Warning Alerts (P2 - < 4 hours)

| Alert | Condition | Duration | Action |
|-------|-----------|----------|--------|
| Elevated Latency | p95 > 2s | 15 min | Log alert |
| Disk Space Low | < 500MB free | - | Slack alert |
| Memory Pressure | > 80% used | 15 min | Log alert |
| Audit Write Backlog | > 1000 pending | 10 min | Slack alert |

### 2.4 Info Alerts (P3 - Next business day)

| Alert | Condition | Duration | Action |
|-------|-----------|----------|--------|
| Unusual Traffic Pattern | Deviation > 2 std | 1 hour | Log only |
| New Error Type | First occurrence | - | Log + tag |
| Deprecation Warning | Legacy endpoint called | - | Log only |

---

## 3. Dashboard Panels

### 3.1 Overview Dashboard

```
+------------------------------------------+
|  Request Rate (req/s)     Error Rate (%) |
|  [LINE CHART]             [LINE CHART]   |
+------------------------------------------+
|  Latency p50/p95/p99      Active Users   |
|  [LINE CHART]             [GAUGE]        |
+------------------------------------------+
|  Top Errors               Top Slow Routes|
|  [TABLE]                  [TABLE]        |
+------------------------------------------+
```

### 3.2 GovCon Dashboard

```
+------------------------------------------+
|  Reconciliation Runs      Audit Writes   |
|  [COUNTER]                [COUNTER]      |
+------------------------------------------+
|  Timesheet Submissions    Variance Rate  |
|  [LINE CHART]             [LINE CHART]   |
+------------------------------------------+
|  Export Success Rate      Evidence Chain |
|  [GAUGE]                  [STATUS]       |
+------------------------------------------+
```

### 3.3 Security Dashboard

```
+------------------------------------------+
|  Rate Limit Rejections    Auth Failures  |
|  [LINE CHART]             [LINE CHART]   |
+------------------------------------------+
|  Top Blocked IPs          Replay Attempts|
|  [TABLE]                  [COUNTER]      |
+------------------------------------------+
|  Kill-Switch Status       Incident Mode  |
|  [STATUS GRID]            [STATUS]       |
+------------------------------------------+
```

---

## 4. Sentry Configuration

### 4.1 Error Grouping

Errors are grouped by:
1. Exception type
2. Stack trace fingerprint
3. request_id (for correlation)

### 4.2 Ignored Errors

```python
# Errors that should NOT trigger alerts
IGNORED_ERRORS = [
    "HTTPException(401)",  # Normal auth failures
    "HTTPException(404)",  # Normal not found
    "HTTPException(422)",  # Validation errors
    "HTTPException(429)",  # Rate limiting
]
```

### 4.3 Performance Sampling

```python
# Sentry performance config
traces_sample_rate = 1.0  # 100% in production (adjust for scale)
```

---

## 5. Log Formats

### 5.1 Structured Log Fields

Every log entry includes:

```json
{
  "timestamp": "2026-01-26T12:00:00Z",
  "level": "INFO|WARN|ERROR",
  "request_id": "uuid",
  "org_id": "org_xxx",
  "user_id": "user_xxx",
  "path": "/api/...",
  "method": "GET|POST|...",
  "status_code": 200,
  "duration_ms": 45,
  "message": "..."
}
```

### 5.2 Log Search Patterns

```bash
# Find all errors for a request
request_id:abc123

# Find all requests for an org
org_id:org_xxx level:ERROR

# Find slow requests
duration_ms:>1000

# Find rate limited requests
status_code:429
```

---

## 6. False Positive Handling

### 6.1 Known False Positives

| Pattern | Reason | Action |
|---------|--------|--------|
| 401 on OPTIONS | CORS preflight | Ignore |
| 429 burst | Dashboard refresh | Threshold > 10/min |
| 404 on /favicon.ico | Browser request | Ignore |
| DB timeout on cold start | Render spin-up | Ignore first 30s |

### 6.2 Alert Tuning

Adjust thresholds based on:
1. Historical baseline (7-day average)
2. Time of day (lower at night)
3. Business events (launches, announcements)

---

## 7. Incident Detection Signals

### 7.1 Leading Indicators

Watch for these BEFORE outage:

| Signal | Meaning | Lead Time |
|--------|---------|-----------|
| Latency creep | Resource exhaustion | 5-15 min |
| Error rate uptick | Bug or dependency issue | 2-5 min |
| Rate limit increase | Attack or load spike | 1-2 min |
| Memory growth | Leak or cache issue | 15-30 min |

### 7.2 Correlation Rules

```
IF error_rate > 5%
AND latency_p99 > 3s
AND db_errors > 0
THEN database_issue (confidence: high)

IF rate_limit_rejections > 100/min
AND unique_ips < 10
THEN possible_attack (confidence: medium)

IF auth_failures > 50/min
AND unique_users > 20
THEN possible_credential_stuffing (confidence: medium)
```

---

## 8. Monitoring Endpoints

### 8.1 Health Checks

| Endpoint | Purpose | Interval |
|----------|---------|----------|
| `GET /health` | Full health with DB | 30s |
| `GET /health/ping` | Quick liveness | 10s |
| `GET /system/health` | System + incident status | 30s |

### 8.2 Diagnostics (Admin Only)

| Endpoint | Purpose |
|----------|---------|
| `GET /system/state` | Incident mode, rollback info |
| `GET /api/killswitch/status` | Kill-switch states |
| `GET /api/diagnostics/status` | Internal diagnostics |

---

## Appendix A: Metric Collection Scripts

### Health Check Script

```bash
#!/bin/bash
# health_check.sh

RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" \
  https://reconai-backend.onrender.com/health)

if [ "$RESPONSE" != "200" ]; then
  echo "CRITICAL: Health check failed with status $RESPONSE"
  exit 2
fi

echo "OK: Health check passed"
exit 0
```

### Latency Check Script

```bash
#!/bin/bash
# latency_check.sh

START=$(date +%s%N)
curl -s https://reconai-backend.onrender.com/health > /dev/null
END=$(date +%s%N)

LATENCY=$(( ($END - $START) / 1000000 ))

if [ $LATENCY -gt 5000 ]; then
  echo "CRITICAL: Latency ${LATENCY}ms exceeds 5s threshold"
  exit 2
elif [ $LATENCY -gt 2000 ]; then
  echo "WARNING: Latency ${LATENCY}ms exceeds 2s threshold"
  exit 1
fi

echo "OK: Latency ${LATENCY}ms"
exit 0
```
