# Render Environment Variables Setup

## CRITICAL: Production Configuration

**Go to Render Dashboard:** https://dashboard.render.com

1. Select the `reconai-backend` service
2. Go to **Environment** tab
3. Add/Update the following variables:

---

## Required Environment Variables

### 1. Change Environment Mode
```
ENVIRONMENT = production
```
(Currently set to "development" - needs to be changed)

### 2. Database Configuration

**Option A: Keep SQLite (Quick Start)**
```
DATABASE_URL = sqlite:///data/reconai.db
```

**Option B: Upgrade to PostgreSQL (Recommended for Production)**
1. In Render Dashboard, create a new PostgreSQL database (free tier available)
2. Copy the Internal Database URL
3. Set:
```
DATABASE_URL = postgresql://user:password@hostname/database
```

### 3. Clerk Authentication
```
CLERK_SECRET_KEY = sk_test_... (get from Clerk dashboard)
```

### 4. Stripe Payment Processing
```
STRIPE_SECRET_KEY = sk_test_... (get from Stripe dashboard)
STRIPE_WEBHOOK_SECRET = whsec_... (get from Stripe webhooks)
```

### 5. Supabase Database
```
SUPABASE_URL = https://xmnzgaqsytyygtyfrzeo.supabase.co
SUPABASE_ANON_KEY = sb_publishable_Ub9byEiU7FfCviIwKjaxeA_ZJ2xj-1m
SUPABASE_SERVICE_ROLE_KEY = (secret - get from Supabase dashboard)
```

### 6. Plaid Bank Integration
```
PLAID_CLIENT_ID = (get from Plaid dashboard)
PLAID_SECRET = (get from Plaid dashboard)
PLAID_ENV = sandbox
```
Change to `production` when ready for live bank connections.

### 7. CORS Configuration
```
FRONTEND_URL = https://reconai-frontend.vercel.app
CORS_ORIGINS = https://reconai-frontend.vercel.app,https://reconai.vercel.app
```

---

## After Updating

1. Save all environment variables in Render
2. Manually trigger a redeploy (or wait for next git push)
3. Check the logs for any errors
4. Test the health endpoint: https://reconai-backend.onrender.com/health

---

## Verification Steps

### 1. Health Check
```bash
curl https://reconai-backend.onrender.com/health
```

Should return:
```json
{
  "status": "healthy",
  "environment": "production",
  "database": "connected"
}
```

### 2. Check Logs
In Render Dashboard → Logs, verify:
- No authentication errors
- Database connected successfully
- No missing environment variable warnings

### 3. Test API Endpoints
From the frontend, test:
- User authentication
- Plaid link token creation
- Transaction classification
- Report generation

---

## Production Database Migration (PostgreSQL)

### Why Upgrade from SQLite?
- SQLite is file-based and not ideal for production
- PostgreSQL is more robust, scalable, and recommended for production
- Render offers free PostgreSQL tier

### Migration Steps:
1. Create PostgreSQL database in Render
2. Export current SQLite data (if needed)
3. Update DATABASE_URL to PostgreSQL connection string
4. Redeploy - migrations will run automatically
5. Import data if needed

---

## Security Checklist

✅ All secret keys stored in Render (not in code)
✅ ENVIRONMENT set to "production"
✅ CORS_ORIGINS properly configured
✅ Webhook secrets configured
✅ Database properly secured

---

## Next Steps After Setup

1. Test all API endpoints from frontend
2. Verify Clerk authentication works
3. Test Plaid bank connection flow
4. Verify Stripe payment processing
5. Check error monitoring in Sentry
