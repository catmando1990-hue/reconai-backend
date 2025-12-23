# ReconAI - Required API Keys & Configuration

## Quick Start Checklist

Before deploying ReconAI, you'll need to obtain the following API keys and credentials:

- [ ] Clerk Authentication Keys
- [ ] Encryption Key (already generated)
- [ ] Anthropic Claude API Key (optional, for AI classification)
- [ ] Plaid API Keys (optional, for bank connections)
- [ ] Sentry DSN (optional, for error monitoring)
- [ ] Email Service API Key (optional, for notifications)

---

## 1. Encryption Key (CRITICAL) ⚠️

**Status:** ✅ **ALREADY GENERATED**

**Value:**
```
BS+zhdzM7RsavgVTrK8nyIjFPLNSQCIwJl6RLEzqdU8=
```

**Environment Variable:**
```env
ENCRYPTION_KEY=BS+zhdzM7RsavgVTrK8nyIjFPLNSQCIwJl6RLEzqdU8=
```

**⚠️ CRITICAL SECURITY NOTES:**
- This key encrypts all uploaded receipts and files using AES-256-GCM
- **NEVER** commit this key to git or share it publicly
- **BACK IT UP** securely - if lost, encrypted files are unrecoverable
- Store in password manager (1Password, LastPass, etc.)
- Use the same key across all environments for consistency
- DO NOT regenerate - will make existing encrypted files unreadable

**What it's used for:**
- Encrypting receipt files before storage
- Decrypting receipt files on download
- Ensuring data-at-rest security

---

## 2. Clerk Authentication (REQUIRED)

**What is it?** User authentication and session management.

**Sign up:** https://dashboard.clerk.com

**Cost:**
- Free tier: Up to 10,000 Monthly Active Users (MAU)
- Pro: $25/month + $0.02/MAU over 10K

### Setup Steps:

1. **Create Account**
   - Go to https://clerk.com
   - Sign up with Google/GitHub or email
   - Create a new application

2. **Configure Authentication Methods**
   - Enable Email/Password
   - Enable Google OAuth (recommended)
   - Enable GitHub OAuth (optional)
   - Enable Microsoft OAuth (for enterprise customers)

3. **Get API Keys**
   - Go to Dashboard → API Keys
   - Copy the following:

```env
CLERK_SECRET_KEY=sk_test_xxxxxxxxxxxxxxxxxxxxxxxxxx
CLERK_PUBLISHABLE_KEY=pk_test_xxxxxxxxxxxxxxxxxxxxxxxxxx
```

4. **Configure Redirect URLs**
   - Development: `http://localhost:3000`
   - Production: `https://your-domain.com`

5. **Session Configuration**
   - Session lifetime: 7 days (recommended)
   - Multi-session: Enabled
   - Refresh tokens: Enabled

**What it's used for:**
- User sign-up and sign-in
- JWT token generation and validation
- Session management
- Multi-factor authentication (MFA)
- User profile management

---

## 3. Anthropic Claude API (OPTIONAL)

**What is it?** AI-powered transaction classification fallback.

**Sign up:** https://console.anthropic.com

**Cost:**
- Pay-as-you-go: ~$0.003 per transaction classification
- Estimated: $10-50/month depending on volume
- No free tier (pay per API call)

### Setup Steps:

1. **Create Account**
   - Go to https://console.anthropic.com
   - Sign up with email
   - Verify your email

2. **Add Payment Method**
   - Go to Billing
   - Add credit card
   - Set budget alerts (recommended: $50/month)

3. **Create API Key**
   - Go to API Keys
   - Click "Create Key"
   - Copy the key immediately (shown only once)

```env
ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

4. **Optional: Set Model**
```env
CLAUDE_MODEL=claude-3-5-sonnet-20241022
```

**What it's used for:**
- Transaction classification when deterministic rules don't match
- Merchant categorization
- Expense description enhancement
- Tax category suggestions

**Note:** The system works without this key using deterministic classification (500+ merchant patterns). Claude is only used as a fallback for unknown merchants.

---

## 4. Plaid Bank Integration (OPTIONAL)

**What is it?** Connect to 12,000+ banks for automatic transaction import.

**Sign up:** https://dashboard.plaid.com

**Cost:**
- Sandbox: Free (fake data for testing)
- Development: Free up to 100 bank connections
- Production: $0.10-0.30 per connected account/month

### Setup Steps:

1. **Create Account**
   - Go to https://plaid.com
   - Sign up for developer account
   - Complete company information

2. **Get API Keys**
   - Go to Team Settings → Keys
   - Select environment (Sandbox for testing)

```env
PLAID_CLIENT_ID=xxxxxxxxxxxxxxxxxx
PLAID_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
PLAID_ENV=sandbox
```

3. **Environment Options**
   - `sandbox` - Fake banks, free, for testing
   - `development` - Real banks, 100 connections free
   - `production` - Real banks, paid, unlimited

4. **Enable Products**
   - Auth (account verification)
   - Transactions (transaction history)
   - Balance (account balances)

**What it's used for:**
- Bank account connections
- Automatic transaction import
- Account balance monitoring
- Real-time transaction updates

**Note:** Not required. Users can manually upload receipts and enter transactions without Plaid.

---

## 5. Sentry Error Monitoring (OPTIONAL)

**What is it?** Error tracking and performance monitoring.

**Sign up:** https://sentry.io

**Cost:**
- Free: 5,000 errors/month
- Team: $26/month for 50,000 errors
- Business: Custom pricing

### Setup Steps:

1. **Create Account**
   - Go to https://sentry.io
   - Sign up with GitHub/Google/email

2. **Create Project**
   - Click "Create Project"
   - Select "Python" → "FastAPI"
   - Name: "ReconAI Backend"

3. **Get DSN**
   - Copy the DSN from project settings

```env
SENTRY_DSN=https://xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx@o123456.ingest.sentry.io/7890123
ENVIRONMENT=production
```

**What it's used for:**
- Real-time error alerts
- Stack trace capture
- Performance monitoring
- Release tracking
- User context on errors

**Highly recommended for production!**

---

## 6. Email Service (OPTIONAL)

**What is it?** Send invoice emails, payment reminders, tax deadline notifications.

**Recommended:** Resend (https://resend.com)

**Cost:**
- Free: 3,000 emails/month
- Pro: $20/month for 50,000 emails

### Setup Steps:

1. **Create Account**
   - Go to https://resend.com
   - Sign up with email

2. **Verify Domain** (for production)
   - Add DNS records to your domain
   - Verify ownership

3. **Get API Key**
   - Go to API Keys
   - Create new key

```env
RESEND_API_KEY=re_xxxxxxxxxxxxxxxxxx
```

**Alternative Services:**
- SendGrid (https://sendgrid.com)
- Mailgun (https://mailgun.com)
- AWS SES (https://aws.amazon.com/ses/)

**What it's used for:**
- Invoice email delivery
- Payment receipts
- Payment reminder emails
- Tax deadline notifications
- Password reset emails (handled by Clerk)

**Note:** Email is optional. Users can download invoices as PDFs without email functionality.

---

## 7. CORS Configuration

**What is it?** Allow frontend to make API requests.

```env
# For development (uses defaults if not set)
CORS_ORIGINS=

# For production
CORS_ORIGINS=https://app.reconai.com,https://reconai.com
```

**Default CORS origins (if not set):**
- http://localhost:5173 (Vite)
- http://localhost:3000 (Next.js)
- http://localhost:3001
- https://reconai-frontend.onrender.com
- https://reconai-frontend.vercel.app
- Plus regex: `^https://.*\.vercel\.app$` (all Vercel preview deployments)

---

## Complete .env Template

Create a `.env` file in the backend root:

```bash
# =============================================================================
# ReconAI Backend - Environment Variables
# =============================================================================

# -----------------------------------------------------------------------------
# DATABASE
# -----------------------------------------------------------------------------
DB_PATH=./data/reconai.db

# -----------------------------------------------------------------------------
# ENCRYPTION (CRITICAL - DO NOT LOSE THIS KEY!)
# -----------------------------------------------------------------------------
ENCRYPTION_KEY=BS+zhdzM7RsavgVTrK8nyIjFPLNSQCIwJl6RLEzqdU8=

# -----------------------------------------------------------------------------
# AUTHENTICATION (REQUIRED)
# -----------------------------------------------------------------------------
# Get from: https://dashboard.clerk.com → API Keys
CLERK_SECRET_KEY=sk_test_your_key_here
CLERK_PUBLISHABLE_KEY=pk_test_your_key_here

# -----------------------------------------------------------------------------
# AI SERVICES (OPTIONAL - for transaction classification)
# -----------------------------------------------------------------------------
# Get from: https://console.anthropic.com → API Keys
ANTHROPIC_API_KEY=sk-ant-your_key_here
CLAUDE_MODEL=claude-3-5-sonnet-20241022

# -----------------------------------------------------------------------------
# BANK INTEGRATION (OPTIONAL - for automatic transaction import)
# -----------------------------------------------------------------------------
# Get from: https://dashboard.plaid.com → Team Settings → Keys
PLAID_CLIENT_ID=your_client_id_here
PLAID_SECRET=your_secret_here
PLAID_ENV=sandbox  # Options: sandbox, development, production

# -----------------------------------------------------------------------------
# ERROR MONITORING (OPTIONAL - highly recommended for production)
# -----------------------------------------------------------------------------
# Get from: https://sentry.io → Create Project → Settings
SENTRY_DSN=https://your_dsn@sentry.io/project_id
ENVIRONMENT=production  # Options: development, staging, production

# -----------------------------------------------------------------------------
# EMAIL SERVICE (OPTIONAL - for invoice emails, notifications)
# -----------------------------------------------------------------------------
# Get from: https://resend.com → API Keys
RESEND_API_KEY=re_your_key_here

# -----------------------------------------------------------------------------
# CORS (OPTIONAL - uses defaults if not set)
# -----------------------------------------------------------------------------
CORS_ORIGINS=http://localhost:3000,https://your-domain.com

# -----------------------------------------------------------------------------
# STRIPE (OPTIONAL - for subscription payments)
# -----------------------------------------------------------------------------
# Get from: https://dashboard.stripe.com → Developers → API Keys
STRIPE_SECRET_KEY=sk_test_your_key_here
STRIPE_PUBLISHABLE_KEY=pk_test_your_key_here
STRIPE_WEBHOOK_SECRET=whsec_your_webhook_secret_here
```

---

## Minimum Configuration (Development)

To get started with minimal setup:

```env
# Bare minimum
DB_PATH=./data/reconai.db
ENCRYPTION_KEY=BS+zhdzM7RsavgVTrK8nyIjFPLNSQCIwJl6RLEzqdU8=
CLERK_SECRET_KEY=sk_test_your_key_here
```

This will run the backend with:
- ✅ User authentication (Clerk)
- ✅ File encryption (AES-256)
- ✅ All bookkeeping features
- ✅ All invoicing & AR features
- ✅ All bills & AP features
- ✅ All financial reports
- ✅ All tax intelligence
- ❌ AI transaction classification (uses deterministic rules)
- ❌ Bank account connections (manual entry only)
- ❌ Error monitoring (console logs only)
- ❌ Email notifications (download PDFs only)

---

## Production Configuration (Recommended)

For production deployment:

```env
# All required keys
DB_PATH=./data/reconai.db
ENCRYPTION_KEY=BS+zhdzM7RsavgVTrK8nyIjFPLNSQCIwJl6RLEzqdU8=
CLERK_SECRET_KEY=sk_live_your_key_here
ANTHROPIC_API_KEY=sk-ant-your_key_here
SENTRY_DSN=https://your_dsn@sentry.io/project_id
ENVIRONMENT=production
CORS_ORIGINS=https://app.reconai.com
```

Optional but recommended:
- Plaid (for bank connections)
- Resend (for email notifications)

---

## Security Best Practices

1. **Never commit .env to git**
   - .env is already in .gitignore
   - Use environment variables in production

2. **Rotate keys regularly**
   - Clerk: Rotate every 90 days
   - Anthropic: Rotate every 90 days
   - Plaid: Rotate every 90 days

3. **Use separate keys per environment**
   - Development: `sk_test_...`
   - Production: `sk_live_...`

4. **Store encryption key securely**
   - Back up to password manager
   - Store offline backup
   - Never regenerate (will break encrypted files)

5. **Monitor API usage**
   - Set budget alerts on all services
   - Monitor Anthropic costs
   - Monitor Plaid connection counts

6. **Use secrets management in production**
   - AWS Secrets Manager
   - Render Environment Variables
   - Railway Environment Variables
   - Docker Secrets

---

## Cost Summary

### Free Tier (Development)
- Clerk: Free (up to 10K MAU)
- Sentry: Free (up to 5K errors/month)
- Resend: Free (up to 3K emails/month)
- Plaid: Free (Development env, 100 connections)
- **Total: $0/month**

### Recommended Production (Small Business)
- Clerk: Free (under 10K MAU)
- Anthropic: $20/month (estimated)
- Plaid Development: Free (under 100 connections)
- Sentry: Free tier
- Resend: Free tier
- **Total: ~$20/month**

### High Volume Production
- Clerk Pro: $25/month
- Anthropic: $50/month
- Plaid Production: $100/month (estimated)
- Sentry Team: $26/month
- Resend Pro: $20/month
- **Total: ~$221/month**

---

## Support & Resources

- **Clerk Docs:** https://clerk.com/docs
- **Anthropic Docs:** https://docs.anthropic.com
- **Plaid Docs:** https://plaid.com/docs
- **Sentry Docs:** https://docs.sentry.io
- **Resend Docs:** https://resend.com/docs

---

## Next Steps

1. ✅ Copy the encryption key (already generated)
2. ⬜ Sign up for Clerk and get API keys
3. ⬜ (Optional) Sign up for Anthropic for AI classification
4. ⬜ (Optional) Sign up for Plaid for bank connections
5. ⬜ (Optional) Sign up for Sentry for error monitoring
6. ⬜ Create .env file with your keys
7. ⬜ Test backend locally
8. ⬜ Deploy to production
9. ⬜ Configure production environment variables
10. ⬜ Test end-to-end flow

**🚀 Ready to deploy!**
