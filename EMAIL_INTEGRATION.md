# Email Integration - Resend

**Date:** December 22, 2025
**Status:** ✅ Integrated

---

## Overview

ReconAI uses **Resend** for transactional emails. The integration is fully configured and ready to use.

---

## Configuration

### API Key

**Production API Key:** `re_UytakvdE_8TeYtsbxcNWhStzk3eTmiRYe`

### Environment Variables

Add to your `.env` file:

```env
RESEND_API_KEY=re_UytakvdE_8TeYtsbxcNWhStzk3eTmiRYe
RESEND_FROM_EMAIL=noreply@reconai.com
RESEND_FROM_NAME=ReconAI
```

### Installation

```bash
pip install resend>=0.8.0
```

---

## Email Service

Location: [app/services/email_service.py](c:\reconai-backend\app\services\email_service.py)

### Features

- ✅ Resend integration with automatic initialization
- ✅ Graceful degradation if not configured
- ✅ Pre-built email templates
- ✅ HTML email with inline CSS
- ✅ Email tagging for tracking
- ✅ Error handling (non-blocking)

---

## Available Email Templates

### 1. Welcome Email

Sent automatically when new user signs up.

**Trigger:** `/api/auth/signup`

**Usage:**
```python
from app.services.email_service import email_service, EmailRecipient

email_service.send_welcome_email(
    to=EmailRecipient(email="user@example.com", name="John"),
    user_name="John",
    organization_name="Veteran Consulting LLC",
    tier="freelancer"
)
```

**Content:**
- Welcome message
- Subscription tier badge
- Feature list
- Dashboard link
- Getting started resources
- Support contact

---

### 2. Team Invitation Email

For inviting team members to organization.

**Trigger:** Manual (to be integrated into `/api/organizations/{org_id}/members`)

**Usage:**
```python
email_service.send_team_invite_email(
    to="newmember@example.com",
    inviter_name="John Smith",
    organization_name="Veteran Consulting LLC",
    role="bookkeeper",
    invite_link="https://app.reconai.com/invite/abc123"
)
```

**Content:**
- Invitation from user
- Organization name
- Assigned role
- Accept invitation button
- Expiration notice (7 days)

---

### 3. Trial Ending Reminder

Remind users before trial expires.

**Trigger:** Scheduled job (to be implemented)

**Usage:**
```python
email_service.send_trial_ending_email(
    to="user@example.com",
    user_name="John",
    organization_name="Veteran Consulting LLC",
    days_remaining=3,
    upgrade_link="https://app.reconai.com/billing/upgrade"
)
```

**Content:**
- Days remaining warning
- Feature list reminder
- Upgrade button
- Special offers (veteran discount, annual billing)

---

### 4. Password Reset

For password reset requests (if using password auth).

**Usage:**
```python
email_service.send_password_reset_email(
    to="user@example.com",
    user_name="John",
    reset_link="https://app.reconai.com/reset-password/token123"
)
```

**Content:**
- Reset password button
- Expiration notice (1 hour)
- Security warning

---

### 5. Monthly Report

Send monthly financial summary.

**Trigger:** Scheduled job (first of month)

**Usage:**
```python
email_service.send_monthly_report_email(
    to="user@example.com",
    user_name="John",
    month="December 2025",
    total_transactions=247,
    business_expenses=12450.75,
    personal_expenses=3200.50,
    report_link="https://app.reconai.com/reports/2025/12"
)
```

**Content:**
- Monthly statistics
- Transaction count
- Business/personal expense breakdown
- View full report button
- Next steps checklist

---

## Custom Emails

Send custom emails using the base method:

```python
from app.services.email_service import email_service

email_service.send_email(
    to="user@example.com",  # or EmailRecipient object or list
    subject="Custom Subject",
    html="<h1>HTML content</h1>",
    text="Plain text version",  # optional
    reply_to="support@reconai.com",  # optional
    tags=[{"name": "category", "value": "custom"}]  # optional
)
```

---

## Email Templates Design

All emails feature:
- **Responsive HTML** - Works on all devices
- **Branded header** - Purple gradient with ReconAI branding
- **Clean layout** - Professional, easy to read
- **Call-to-action buttons** - Clear next steps
- **Footer** - Contact info, veteran benefits notice

### Brand Colors

- **Primary:** `#667eea` (Purple)
- **Gradient:** `linear-gradient(135deg, #667eea 0%, #764ba2 100%)`
- **Success:** `#10b981` (Green)
- **Warning:** `#f59e0b` (Orange)
- **Background:** `#f9fafb` (Light gray)

---

## Integration Points

### ✅ Currently Integrated

1. **Signup Flow** ([app/routers/auth.py:259-269](c:\reconai-backend\app\routers\auth.py))
   - Welcome email sent after successful signup
   - Non-blocking (signup succeeds even if email fails)

### 🔜 To Be Integrated

1. **Team Invitations** (`/api/organizations/{org_id}/members`)
   - Send invite email when adding new member
   - Include organization details and role

2. **Trial Reminders** (Scheduled job)
   - Check for trials ending in 3 days
   - Send reminder with upgrade link

3. **Password Reset** (If using password auth)
   - Send reset link when requested

4. **Monthly Reports** (Scheduled job)
   - Run on 1st of each month
   - Send summary to all active users

5. **Upgrade Confirmation**
   - Send when user upgrades tier
   - Include new feature list

6. **Welcome Series** (Drip campaign)
   - Day 1: Welcome email
   - Day 3: Getting started tips
   - Day 7: Feature highlights
   - Day 13: Trial ending reminder

---

## Resend Dashboard

**Login:** https://resend.com/login

**Features Available:**
- Email logs (see what was sent)
- Delivery status
- Bounce/complaint tracking
- Domain verification
- Email templates (visual editor)
- Analytics
- Webhooks (for delivery events)

---

## Domain Verification

To send from `@reconai.com`, verify domain in Resend:

1. Go to Resend Dashboard → Domains
2. Add domain: `reconai.com`
3. Add DNS records:
   - SPF record
   - DKIM record
   - DMARC record (optional)
4. Wait for verification (5-30 minutes)

Until verified, emails will come from `@onresend.dev` (sandbox).

---

## Testing Emails

### Local Testing

```bash
# Set API key in .env
RESEND_API_KEY=re_UytakvdE_8TeYtsbxcNWhStzk3eTmiRYe

# Run Python shell
python

# Test email
from app.services.email_service import email_service

email_service.send_email(
    to="your-email@example.com",
    subject="Test Email",
    html="<h1>It works!</h1>"
)
```

### Sandbox Mode

Resend automatically uses sandbox mode for unverified domains:
- Emails sent to verified email addresses only
- No spam risk
- Perfect for testing

---

## Error Handling

The email service is designed to **never fail the main operation**:

```python
# Email errors are caught and logged
try:
    email_service.send_welcome_email(...)
except Exception as e:
    print(f"Failed to send welcome email: {str(e)}")
    # Signup still succeeds!
```

### Graceful Degradation

If Resend is not configured:
- `email_service.enabled = False`
- Emails are logged to console
- No errors thrown
- Application continues normally

---

## Best Practices

1. **Use Templates** - Pre-built templates ensure consistent branding
2. **Add Tags** - Tag emails for tracking (`category: welcome`, etc.)
3. **Include Plain Text** - Better deliverability (auto-generated if not provided)
4. **Test Thoroughly** - Always test emails before production
5. **Monitor Delivery** - Check Resend dashboard for bounces/complaints
6. **Verify Domain** - Better deliverability with verified domain
7. **Non-Blocking** - Never let email failures break core functionality

---

## Email Limits

**Resend Free Tier:**
- 3,000 emails/month
- 100 emails/day

**Resend Pro Tier:**
- 50,000 emails/month
- Unlimited daily sending
- **$20/month**

**For ReconAI:**
- Start with free tier
- Upgrade to Pro when hitting limits
- Monitor usage in Resend dashboard

---

## Future Enhancements

1. **Email Preferences** - Let users opt out of certain emails
2. **Unsubscribe Links** - One-click unsubscribe (required for marketing)
3. **A/B Testing** - Test different email versions
4. **Email Analytics** - Track open rates, click rates
5. **Webhooks** - Listen for delivery events
6. **Visual Template Editor** - Use Resend's visual editor
7. **Localization** - Multi-language email support

---

## Support

**Resend Documentation:** https://resend.com/docs
**Resend Support:** support@resend.com
**API Reference:** https://resend.com/docs/api-reference

---

**Email integration complete! ✅**
