# ReconAI Backend Production Runbook

**Version:** 1.0.0
**Last Updated:** 2026-01-26
**Status:** PRODUCTION READY

---

## 1. Deployment

### 1.1 Normal Deploy (Render Auto-Deploy)

Render auto-deploys on push to `main` branch.

```bash
# Verify before push
git status
git diff main

# Push to deploy
git push origin main
```

**Post-Deploy Verification:**
```bash
# Health check
curl -s https://reconai-backend.onrender.com/health | jq

# Expected response:
# {
#   "status": "healthy",
#   "service": "reconai-backend",
#   "version": "1.0.0",
#   "environment": "production",
#   "database": "connected"
# }
```

### 1.2 Manual Deploy via Render Dashboard

1. Navigate to: https://dashboard.render.com/
2. Select `reconai-backend` service
3. Click **Manual Deploy** > **Deploy latest commit**
4. Monitor deploy logs for errors

### 1.3 Environment Variables

**CRITICAL:** Never commit secrets. Set in Render Dashboard only:

| Variable | Purpose | Rotation |
|----------|---------|----------|
| `CLERK_SECRET_KEY` | Auth verification | Quarterly |
| `STRIPE_SECRET_KEY` | Payment processing | Quarterly |
| `STRIPE_WEBHOOK_SECRET` | Webhook validation | On regenerate |
| `PLAID_SECRET` | Bank connection | Quarterly |
| `SENTRY_DSN` | Error tracking | Never |
| `ANTHROPIC_API_KEY` | AI classification | Quarterly |

---

## 2. Rollback Procedures

### 2.1 Immediate Rollback (< 5 min)

**Via Render Dashboard:**
1. Go to `reconai-backend` > **Deploys**
2. Find last known-good deploy
3. Click **Rollback to this deploy**
4. Verify health check

**Via Git:**
```bash
# Find last good commit
git log --oneline -10

# Revert
git revert HEAD
git push origin main
```

### 2.2 Database-Aware Rollback

If rollback involves database schema changes:

```bash
# 1. Enable incident mode FIRST
curl -X POST https://reconai-backend.onrender.com/system/incident/on \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# 2. Perform rollback via Render Dashboard

# 3. Verify database state
curl https://reconai-backend.onrender.com/health

# 4. Disable incident mode
curl -X POST https://reconai-backend.onrender.com/system/incident/off \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

### 2.3 API Rollback Endpoint

```bash
# Rollback to last approved deploy run
curl -X POST https://reconai-backend.onrender.com/system/rollback \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

---

## 3. Incident Response

### 3.1 Severity Levels

| Level | Description | Response Time | Escalation |
|-------|-------------|---------------|------------|
| P0 | Complete outage | < 15 min | Immediate |
| P1 | Major feature broken | < 1 hour | Lead dev |
| P2 | Minor feature broken | < 4 hours | On-call |
| P3 | Non-blocking issue | < 24 hours | Next sprint |

### 3.2 Incident Mode

**Enable Incident Mode** (blocks all non-admin requests):
```bash
curl -X POST https://reconai-backend.onrender.com/system/incident/on \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

**Disable Incident Mode:**
```bash
curl -X POST https://reconai-backend.onrender.com/system/incident/off \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

**Check Status:**
```bash
curl https://reconai-backend.onrender.com/system/state
```

### 3.3 Incident Response Flow

```
1. DETECT
   - Sentry alert
   - Health check failure
   - User report

2. ASSESS
   - Check /health endpoint
   - Check /system/state
   - Review Sentry errors
   - Check Render logs

3. CONTAIN
   - Enable incident mode if needed
   - Notify affected users

4. FIX
   - Rollback if possible
   - Hotfix if needed

5. VERIFY
   - Health checks pass
   - No new Sentry errors
   - User confirmation

6. DOCUMENT
   - Update incident log
   - Postmortem if P0/P1
```

---

## 4. Escalation Paths

### 4.1 Technical Escalation

| Role | Contact | When |
|------|---------|------|
| On-Call Dev | Slack #oncall | First response |
| Tech Lead | Direct message | P0/P1 incidents |
| CTO | Phone | Extended outage (>1hr) |

### 4.2 Third-Party Escalation

| Service | Status Page | Support |
|---------|-------------|---------|
| Render | status.render.com | support@render.com |
| Clerk | clerk.dev/status | Discord support |
| Stripe | status.stripe.com | Dashboard support |
| Plaid | status.plaid.com | Dashboard support |
| Sentry | status.sentry.io | support@sentry.io |

---

## 5. Common Operations

### 5.1 View Logs

**Render Dashboard:**
1. Navigate to `reconai-backend` service
2. Click **Logs** tab
3. Filter by time range

**Search for request:**
```bash
# All logs contain request_id
# Search for specific request in Render logs UI
request_id: abc123-def456
```

### 5.2 Check Rate Limits

```bash
# Response headers include:
# X-RateLimit-Limit: 100
# X-RateLimit-Remaining: 95
```

### 5.3 Kill-Switch Operations

```bash
# Check kill-switch status
curl https://reconai-backend.onrender.com/api/killswitch/status

# Kill-switches are env-controlled:
# KILLSWITCH_EXPORTS=true
# KILLSWITCH_INVESTOR_EXPORTS=true
# KILLSWITCH_BENCHMARKS=true
# KILLSWITCH_ML_GOVERNANCE=true
```

### 5.4 Database Operations

**Backup (Manual):**
```bash
# Access Render shell
# SQLite db is at /var/data/reconai.db
cp /var/data/reconai.db /var/data/reconai.db.backup
```

**Check Integrity:**
```bash
curl https://reconai-backend.onrender.com/health
# database: "connected" = OK
# database: "error: ..." = PROBLEM
```

---

## 6. Maintenance Windows

### 6.1 Scheduled Maintenance

1. Announce 24h in advance via status page
2. Enable incident mode at maintenance start
3. Perform maintenance
4. Verify health checks
5. Disable incident mode
6. Update status page

### 6.2 Emergency Maintenance

1. Enable incident mode immediately
2. Notify users ASAP
3. Perform emergency fix
4. Verify health checks
5. Disable incident mode
6. Postmortem within 24h

---

## 7. Contacts

| Role | Name | Contact |
|------|------|---------|
| Project Owner | - | - |
| Tech Lead | - | - |
| On-Call | - | Slack #oncall |

**Slack Channels:**
- #reconai-backend - General discussion
- #reconai-oncall - Incident response
- #reconai-alerts - Automated alerts

---

## Appendix A: Quick Reference

```bash
# Health check
curl https://reconai-backend.onrender.com/health

# System state
curl https://reconai-backend.onrender.com/system/state

# Enable incident mode
curl -X POST https://reconai-backend.onrender.com/system/incident/on \
  -H "Authorization: Bearer $TOKEN"

# Disable incident mode
curl -X POST https://reconai-backend.onrender.com/system/incident/off \
  -H "Authorization: Bearer $TOKEN"

# Check kill-switch
curl https://reconai-backend.onrender.com/api/killswitch/status
```
