# ReconAI Backend Deployment Guide

**Status:** Ready to deploy with HTTPS
**Platforms:** Render (recommended), Railway, or any Docker platform

---

## 🚀 Quick Deploy (Render - Easiest)

### Step 1: Push Your Code to GitHub

```bash
git add render.yaml Dockerfile .dockerignore railway.json DEPLOYMENT_GUIDE.md
git commit -m "feat: add deployment configuration for Render/Railway"
git push origin feature/clerk-auth
```

### Step 2: Deploy to Render

1. **Go to:** https://dashboard.render.com/
2. **Sign up/Login** with GitHub
3. **Click:** "New +" → "Blueprint"
4. **Connect your repository:** `reconai-backend`
5. **Branch:** `feature/clerk-auth` (or `main` after merging)
6. **Render will auto-detect** `render.yaml`
7. **Click:** "Apply"

### Step 3: Set Environment Variables

In Render dashboard, go to your service → Environment:

```bash
# Required
ENVIRONMENT=production
CLERK_SECRET_KEY=sk_test_...  # Your Clerk key
STRIPE_SECRET_KEY=sk_test_... # Your Stripe key
PLAID_CLIENT_ID=...
PLAID_SECRET=...
SUPABASE_URL=...
SUPABASE_ANON_KEY=...
SUPABASE_SERVICE_ROLE_KEY=...

# Optional
STRIPE_WEBHOOK_SECRET=whsec_...
PLAID_ENV=sandbox
FRONTEND_URL=https://reconai-frontend.vercel.app
```

### Step 4: Deploy!

- Render will automatically build and deploy
- You'll get a URL like: `https://reconai-backend.onrender.com`
- **HTTPS is automatic and free!** ✅

---

## 🔧 Alternative: Railway (Also Free HTTPS)

### Step 1: Deploy to Railway

1. **Go to:** https://railway.app/
2. **Sign up/Login** with GitHub
3. **Click:** "New Project" → "Deploy from GitHub repo"
4. **Select:** `reconai-backend`
5. **Railway auto-detects** Dockerfile

### Step 2: Add Environment Variables

In Railway dashboard:

```bash
ENVIRONMENT=production
CLERK_SECRET_KEY=...
STRIPE_SECRET_KEY=...
# ... (same as Render)
```

### Step 3: Get Your URL

- Railway gives you: `https://your-app.up.railway.app`
- **HTTPS is automatic and free!** ✅

---

## 📊 Deployment Comparison

| Feature | Render | Railway | Vercel |
|---------|--------|---------|--------|
| **Free HTTPS** | ✅ Yes | ✅ Yes | ✅ Yes |
| **Free Tier** | 750 hrs/month | $5/month credit | ❌ No (Python) |
| **Python Support** | ✅ Native | ✅ Docker | ❌ No |
| **Auto-deploy** | ✅ Yes | ✅ Yes | ✅ Yes |
| **Database** | ✅ Disk support | ✅ Volume support | ❌ Difficult |
| **Best For** | **FastAPI apps** | Docker apps | Next.js only |

**Recommendation:** Use **Render** for backend, **Vercel** for frontend

---

## 🔒 HTTPS Configuration (Automatic!)

Both Render and Railway automatically provide:
- ✅ **Free SSL/TLS certificates** (Let's Encrypt)
- ✅ **Auto-renewal** (every 90 days)
- ✅ **HTTPS redirect** (HTTP → HTTPS)
- ✅ **TLS 1.2 and 1.3** support
- ✅ **HTTP/2** support

### Verify HTTPS Works

After deployment, test:

```bash
# Check SSL certificate
curl -vI https://your-app.onrender.com/health

# Should see:
# SSL certificate verify ok
# HTTP/2 200
```

---

## 🎯 Post-Deployment Checklist

### 1. Update CORS Settings

Your backend is already configured for:
- `https://reconai-frontend.vercel.app`
- `https://reconai-frontend.onrender.com`

If you deploy to a different URL, update `CORS_ORIGINS` environment variable.

### 2. Update Frontend API URL

In your frontend `.env`:

```bash
# Old (local development)
NEXT_PUBLIC_API_URL=http://localhost:8000

# New (production)
NEXT_PUBLIC_API_URL=https://reconai-backend.onrender.com
```

### 3. Test All Endpoints

```bash
# Health check
curl https://your-backend-url.onrender.com/health

# API docs
open https://your-backend-url.onrender.com/docs

# Test authentication (should return 401)
curl https://your-backend-url.onrender.com/api/user/profile
```

### 4. Enable Production Security

Set this environment variable in Render/Railway:

```bash
ENVIRONMENT=production
```

This enables:
- ✅ HSTS headers (force HTTPS)
- ✅ Trusted host checking
- ✅ Production-grade security settings

---

## 💾 Database Considerations

### Current Setup (SQLite)
- ✅ **Works** on Render with persistent disk
- ✅ **Simple** - no external database needed
- ⚠️ **Limited** - single instance only
- ⚠️ **Not ideal** for high traffic

### For Production at Scale

Consider upgrading to PostgreSQL when you need:
- Multiple backend instances
- Better performance
- More reliability

**Options:**
- **Render PostgreSQL:** $7/month
- **Supabase PostgreSQL:** Free tier available
- **Railway PostgreSQL:** Included in $5/month credit

### Migrate to PostgreSQL (When Ready)

```bash
# Install PostgreSQL adapter
pip install psycopg2-binary

# Update DATABASE_URL
DATABASE_URL=postgresql://user:pass@host:5432/dbname

# Update app/db.py to use PostgreSQL instead of SQLite
```

---

## 🔐 Security Hardening

### SSL/TLS Certificate
✅ **Already handled** by Render/Railway (Let's Encrypt)

### HSTS (Strict Transport Security)
✅ **Already implemented** - enabled when `ENVIRONMENT=production`

### Security Headers
✅ **Already implemented:**
- X-Content-Type-Options: nosniff
- X-Frame-Options: DENY
- X-XSS-Protection: 1; mode=block
- Content-Security-Policy
- Referrer-Policy
- Permissions-Policy

### Rate Limiting
✅ **Already implemented:**
- Auth endpoints: 5/min
- API endpoints: 100/min
- Public endpoints: 3/5min

### Additional Hardening (Optional)

1. **Enable DDoS Protection:**
   - Add Cloudflare in front of your domain
   - Free plan includes basic DDoS protection

2. **Add Monitoring:**
   ```bash
   pip install sentry-sdk
   SENTRY_DSN=https://...
   ```

3. **Database Encryption:**
   - Switch to PostgreSQL with encryption at rest
   - Or use SQLCipher for SQLite encryption

---

## 📱 Custom Domain (Optional)

### Add Your Own Domain

1. **Buy domain** (Namecheap, Google Domains, etc.)

2. **In Render/Railway:**
   - Go to Settings → Custom Domains
   - Add: `api.reconai.com`

3. **Update DNS:**
   - Add CNAME record:
   ```
   api.reconai.com → reconai-backend.onrender.com
   ```

4. **SSL is automatic!**
   - Render/Railway auto-provisions SSL for custom domains
   - Usually takes 5-10 minutes

---

## 🧪 Testing Your Deployment

### Test Security Headers

```bash
curl -I https://your-backend.onrender.com/health
```

Should see:
```
HTTP/2 200
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
content-security-policy: default-src 'self'
strict-transport-security: max-age=31536000; includeSubDomains
```

### Test Rate Limiting

```bash
# Should get rate limited after 5 attempts
for i in {1..10}; do
  curl https://your-backend.onrender.com/api/auth/login
done
```

### Test GDPR Endpoints

```bash
# Should require authentication (401)
curl https://your-backend.onrender.com/api/user/export-data
```

---

## 💰 Pricing

### Render Costs
- **Starter Plan:** $7/month
  - 512MB RAM
  - Shared CPU
  - Good for MVP/testing

- **Standard Plan:** $25/month (recommended for production)
  - 2GB RAM
  - 1 CPU
  - Better performance

- **Persistent Disk:** Free (1GB included)

### Railway Costs
- **Free:** $5/month credit (use carefully)
- **Pro:** $20/month (unlimited usage)
- **Fair usage:** Pay for what you use

### Recommendation
- **MVP/Testing:** Render Starter ($7/month)
- **Production:** Render Standard ($25/month)
- **High Traffic:** Railway Pro ($20/month) or AWS

---

## 🚨 Common Issues

### Issue: "Module not found"
**Fix:** Make sure `requirements.txt` is up to date
```bash
pip freeze > requirements.txt
git add requirements.txt
git commit -m "update requirements"
git push
```

### Issue: "Database locked"
**Fix:** SQLite doesn't handle concurrent writes well
- Solution: Upgrade to PostgreSQL

### Issue: "CORS errors"
**Fix:** Add your frontend URL to `CORS_ORIGINS`
```bash
# In Render dashboard
CORS_ORIGINS=https://your-frontend.vercel.app
```

### Issue: "Environment variables not working"
**Fix:** Don't use `.env` file in production
- Set all env vars in Render/Railway dashboard

---

## ✅ Deployment Success Checklist

After deployment, verify:

- [ ] Backend is accessible via HTTPS
- [ ] `/health` endpoint returns 200
- [ ] `/docs` shows API documentation
- [ ] Security headers are present
- [ ] Rate limiting is working
- [ ] CORS allows your frontend
- [ ] Environment is set to `production`
- [ ] Frontend can connect to backend
- [ ] Authentication works (Clerk)
- [ ] Plaid integration works
- [ ] Database is persisted (test by redeploying)

---

## 🎉 You're Live!

After deployment:

1. **Your backend URL:** `https://reconai-backend.onrender.com`
2. **HTTPS:** ✅ Automatic (Let's Encrypt)
3. **Security:** ✅ Headers, rate limiting, HSTS
4. **Monitoring:** Check Render/Railway dashboard

### Share Your API

- **API Docs:** `https://your-backend.onrender.com/docs`
- **Health Check:** `https://your-backend.onrender.com/health`

---

## 📞 Next Steps

1. **Deploy backend** to Render (10 minutes)
2. **Update frontend** API URL (2 minutes)
3. **Test end-to-end** (30 minutes)
4. **Monitor errors** (ongoing)
5. **Consider PostgreSQL** (when scaling)
6. **Add custom domain** (optional)

---

**You're ready to deploy with free HTTPS!** 🚀

Choose Render for simplest deployment, or Railway if you prefer more control.
