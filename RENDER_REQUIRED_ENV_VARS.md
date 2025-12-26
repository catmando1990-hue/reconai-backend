# Required Environment Variables for Render

## Status: You Have All the Keys! ✅

Based on your local `.env` file, you already have all the necessary API keys. You just need to add them to Render.

---

## Critical Variables to Add to Render NOW

Copy these from your local `.env` file to Render dashboard:

### 1. Clerk Authentication ✅
```bash
CLERK_SECRET_KEY=sk_test_Dhh9Jw3YB2s4fxUHnDGrX8YbJXIeBXGMxNrR4NZ7aR
```

### 2. Stripe Payment Processing ✅
```bash
STRIPE_SECRET_KEY=sk_test_51ShFjNIScwbigM56ezFgKmzhWAhNvMOeG3Pwhep3EHKf5vmyO4zfmaNcne6VOszPGAeCpQkbKrC61nvLHCXVutj300QBhyBCdC
```

**⚠️ Webhook Secret - NEEDS UPDATE:**
```bash
STRIPE_WEBHOOK_SECRET=whsec_your_webhook_secret_here
```
Current value is a placeholder. Get real webhook secret from Stripe dashboard:
1. Go to: https://dashboard.stripe.com/webhooks
2. Add endpoint: `https://reconai-backend.onrender.com/webhooks/stripe`
3. Copy the signing secret

### 3. Supabase Database ✅
```bash
SUPABASE_URL=https://xmnzgaqsytyygtyfrzeo.supabase.co
SUPABASE_ANON_KEY=sb_publishable_Ub9byEiU7FfCviIwKjaxeA_ZJ2xj-1m
SUPABASE_SERVICE_ROLE_KEY=sb_secret_pMPFqWX9sLmlN0vQyXPcHw_EUOIV_ty
```

### 4. Plaid Bank Integration ✅
```bash
PLAID_CLIENT_ID=693ad27ee8cdd3002261534c
PLAID_SECRET=bfe19289a2f037f9beeef7059a6260
PLAID_ENV=sandbox
```

### 5. Anthropic AI (Transaction Classification) ✅
```bash
ANTHROPIC_API_KEY=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
```

### 6. Environment & CORS ✅
```bash
ENVIRONMENT=production
FRONTEND_URL=https://reconai-frontend.vercel.app
CORS_ORIGINS=https://reconai-frontend.vercel.app
```

### 7. Database Path ✅
```bash
DB_PATH=/opt/render/project/src/data/reconai.db
```

### 8. Sentry Error Monitoring ✅
```bash
SENTRY_DSN=https://4ae03465676b18890bdbb86fb6863124@o4510582236839936.ingest.us.sentry.io/4510583036772352
```

### 9. Encryption Key (CRITICAL!) ✅
```bash
ENCRYPTION_KEY=BS+zhdzM7RsavgVTrK8nyIjFPLNSQCIwJl6RLEzqdU8=
```
**⚠️ NEVER LOSE THIS KEY** - encrypted data cannot be recovered without it!

---

## Optional - Can Add Later

These are in your `.env.example` but not currently in use:

### Email (Resend) - Optional
```bash
RESEND_API_KEY=re_UytakvdE_8TeYtsbxcNWhStzk3eTmiRYe
RESEND_FROM_EMAIL=noreply@reconai.com
RESEND_FROM_NAME=ReconAI
```
**Status:** You have a key, but email features aren't implemented yet

### Stripe Price IDs - Optional
Only needed when you set up subscription plans:
```bash
STRIPE_PRICE_INDIVIDUAL_MONTHLY=price_xxxxxxxxxxxx
STRIPE_PRICE_FREELANCER_MONTHLY=price_xxxxxxxxxxxx
# etc...
```
**Status:** Create these in Stripe dashboard when ready

---

## Quick Copy-Paste for Render

Here's everything formatted for quick copy-paste into Render:

```bash
# Authentication
CLERK_SECRET_KEY=sk_test_Dhh9Jw3YB2s4fxUHnDGrX8YbJXIeBXGMxNrR4NZ7aR

# Payments
STRIPE_SECRET_KEY=sk_test_51ShFjNIScwbigM56ezFgKmzhWAhNvMOeG3Pwhep3EHKf5vmyO4zfmaNcne6VOszPGAeCpQkbKrC61nvLHCXVutj300QBhyBCdC
STRIPE_WEBHOOK_SECRET=whsec_GET_FROM_STRIPE_DASHBOARD

# Database
SUPABASE_URL=https://xmnzgaqsytyygtyfrzeo.supabase.co
SUPABASE_ANON_KEY=sb_publishable_Ub9byEiU7FfCviIwKjaxeA_ZJ2xj-1m
SUPABASE_SERVICE_ROLE_KEY=sb_secret_pMPFqWX9sLmlN0vQyXPcHw_EUOIV_ty

# Banking
PLAID_CLIENT_ID=693ad27ee8cdd3002261534c
PLAID_SECRET=bfe19289a2f037f9beeef7059a6260
PLAID_ENV=sandbox

# AI
ANTHROPIC_API_KEY=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

# Environment
ENVIRONMENT=production
DB_PATH=/opt/render/project/src/data/reconai.db

# CORS
FRONTEND_URL=https://reconai-frontend.vercel.app
CORS_ORIGINS=https://reconai-frontend.vercel.app

# Monitoring
SENTRY_DSN=https://4ae03465676b18890bdbb86fb6863124@o4510582236839936.ingest.us.sentry.io/4510583036772352

# Security
ENCRYPTION_KEY=BS+zhdzM7RsavgVTrK8nyIjFPLNSQCIwJl6RLEzqdU8=
```

---

## Action Items

### NOW (10 minutes)
1. ✅ You have all the keys
2. ⚠️ Get real Stripe webhook secret
3. 📋 Copy-paste all variables to Render dashboard
4. 🔄 Redeploy backend on Render

### LATER (Optional)
- Set up Resend email integration
- Create Stripe Price IDs for subscription plans
- Upgrade to PostgreSQL database
- Switch to Plaid production (requires approval)

---

## How to Add to Render

1. Go to: https://dashboard.render.com
2. Select: `reconai-backend` service
3. Click: **Environment** tab
4. Click: **Add Environment Variable**
5. For each variable:
   - Name: Variable name (e.g., `CLERK_SECRET_KEY`)
   - Value: The actual value from above
   - Click: **Add**
6. After adding all variables, click: **Manual Deploy** → **Deploy latest commit**

---

## Verification Checklist

After adding all variables and redeploying, verify:

- [ ] Backend starts without errors
- [ ] Health endpoint returns `{"environment": "production"}`
- [ ] Clerk authentication works
- [ ] Plaid link token creation works
- [ ] Transaction classification works
- [ ] No missing environment variable warnings in logs

---

**Last Updated:** 2025-12-26
**Status:** All keys available, just need to be added to Render
