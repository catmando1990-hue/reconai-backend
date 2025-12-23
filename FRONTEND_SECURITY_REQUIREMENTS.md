# Frontend Security Requirements

**Date:** December 23, 2025
**Backend Status:** ✅ All security endpoints ready
**Frontend Action Required:** Legal pages + privacy features

---

## 🎯 What You Need to Build (Frontend)

The backend security is complete. Now frontend needs to:
1. Create legal pages (privacy, terms, cookies)
2. Add cookie consent banner
3. Implement privacy/security settings pages
4. Add terms acceptance flow

---

## 🚨 CRITICAL - Do Before Launch

### 1. Privacy Policy Page ⚠️ REQUIRED BY LAW
**File:** `app/legal/privacy-policy/page.tsx`

```tsx
export default function PrivacyPolicyPage() {
  return (
    <div className="container max-w-4xl py-12">
      <h1>Privacy Policy</h1>
      <p>Last Updated: December 23, 2025</p>

      {/* Use a template from Termly or TermsFeed */}
      {/* Must include: */}
      {/* - What data we collect */}
      {/* - How we use it */}
      {/* - Third parties (Clerk, Plaid, Stripe, Anthropic) */}
      {/* - User rights (GDPR/CCPA) */}
      {/* - Contact: privacy@reconai.com */}
    </div>
  );
}
```

**Where to get a template:**
- https://www.termsfeed.com/privacy-policy-generator/
- https://www.termly.io/products/privacy-policy-generator/
- Hire a lawyer (best option, $500-2000)

**Must include:**
- ✅ Company name and contact info
- ✅ What data you collect (email, name, financial transactions)
- ✅ Why you collect it (bookkeeping, tax optimization)
- ✅ Third parties: Clerk (auth), Plaid (banking), Stripe (payments), Anthropic (AI)
- ✅ Data retention: 7 years for financial, until deletion for personal
- ✅ User rights: access, export, delete
- ✅ GDPR compliance statement
- ✅ CCPA compliance statement (if serving California users)

---

### 2. Terms of Service Page ⚠️ REQUIRED BY LAW
**File:** `app/legal/terms-of-service/page.tsx`

```tsx
export default function TermsOfServicePage() {
  return (
    <div className="container max-w-4xl py-12">
      <h1>Terms of Service</h1>
      <p>Last Updated: December 23, 2025</p>

      {/* Use a template from Termly or TermsFeed */}
      {/* Must include: */}
      {/* - Service description (bookkeeping SaaS) */}
      {/* - User obligations */}
      {/* - Liability limitations */}
      {/* - Data ownership (users own their data) */}
      {/* - Termination policy */}
    </div>
  );
}
```

---

### 3. Cookie Policy Page ⚠️ GDPR REQUIRED
**File:** `app/legal/cookie-policy/page.tsx`

```tsx
export default function CookiePolicyPage() {
  return (
    <div className="container max-w-4xl py-12">
      <h1>Cookie Policy</h1>

      <h2>Cookies We Use</h2>
      <table>
        <tr>
          <td>reconai-consent</td>
          <td>Stores your cookie consent preference</td>
          <td>1 year</td>
        </tr>
        <tr>
          <td>clerk-session</td>
          <td>Authentication session (managed by Clerk)</td>
          <td>Until logout</td>
        </tr>
      </table>
    </div>
  );
}
```

---

### 4. Cookie Consent Banner ⚠️ GDPR/CCPA REQUIRED
**Install:** `npm install react-cookie-consent`

**File:** `app/layout.tsx` (add to root layout)

```tsx
import CookieConsent from "react-cookie-consent";
import Link from "next/link";

export default function RootLayout({ children }) {
  return (
    <html>
      <body>
        {children}

        <CookieConsent
          location="bottom"
          buttonText="Accept All Cookies"
          declineButtonText="Reject Non-Essential"
          enableDeclineButton
          cookieName="reconai-consent"
          style={{ background: "#2B373B" }}
          buttonStyle={{ background: "#4ade80", color: "#fff", fontSize: "14px" }}
          declineButtonStyle={{ background: "#ef4444", color: "#fff" }}
          expires={365}
        >
          We use cookies to improve your experience and analyze site traffic.{" "}
          <Link href="/legal/cookie-policy" className="underline">
            Learn more
          </Link>
        </CookieConsent>
      </body>
    </html>
  );
}
```

---

### 5. Terms Acceptance Flow ⚠️ REQUIRED
**File:** `app/(dashboard)/onboarding/accept-terms/page.tsx`

Force new users to accept terms on first login:

```tsx
"use client";

import { useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { useRouter } from "next/navigation";

export default function AcceptTermsPage() {
  const { getToken } = useAuth();
  const router = useRouter();
  const [accepted, setAccepted] = useState(false);

  async function handleAccept() {
    if (!accepted) {
      alert("You must accept the Terms of Service to continue");
      return;
    }

    // Store acceptance in backend
    const token = await getToken();
    await fetch("http://localhost:8000/api/user/profile", {
      method: "PUT",
      headers: {
        "Authorization": `Bearer ${token}`,
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        terms_accepted_at: new Date().toISOString(),
        terms_version: "1.0"
      })
    });

    router.push("/dashboard");
  }

  return (
    <div className="container max-w-2xl py-12">
      <h1>Accept Terms of Service</h1>

      <div className="border p-6 my-6 max-h-96 overflow-y-auto">
        {/* Show full terms here */}
        <h2>Terms of Service</h2>
        <p>By using ReconAI, you agree to...</p>
        {/* Include full terms text */}
      </div>

      <label className="flex items-center gap-3">
        <input
          type="checkbox"
          checked={accepted}
          onChange={(e) => setAccepted(e.target.checked)}
        />
        <span>
          I agree to the{" "}
          <a href="/legal/terms-of-service" target="_blank" className="underline">
            Terms of Service
          </a>{" "}
          and{" "}
          <a href="/legal/privacy-policy" target="_blank" className="underline">
            Privacy Policy
          </a>
        </span>
      </label>

      <button
        onClick={handleAccept}
        disabled={!accepted}
        className="mt-6 btn-primary"
      >
        Continue to Dashboard
      </button>
    </div>
  );
}
```

**Add to backend:** Add these fields to `users` table:
```sql
ALTER TABLE users ADD COLUMN terms_accepted_at TEXT;
ALTER TABLE users ADD COLUMN terms_version TEXT;
```

---

## 📱 Privacy & Security Settings Pages

### 6. Privacy Settings Page
**File:** `app/(dashboard)/settings/privacy/page.tsx`

```tsx
"use client";

import { useAuth } from "@clerk/nextjs";

export default function PrivacySettingsPage() {
  const { getToken } = useAuth();

  async function exportData() {
    const token = await getToken();
    const response = await fetch("http://localhost:8000/api/user/export-data", {
      headers: { "Authorization": `Bearer ${token}` }
    });

    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `reconai_data_export_${Date.now()}.json`;
    a.click();
  }

  async function deleteAccount() {
    const confirmation = prompt("Type DELETE to confirm account deletion:");
    if (confirmation !== "DELETE") return;

    const token = await getToken();
    await fetch("http://localhost:8000/api/user/delete-account?confirmation=DELETE", {
      method: "DELETE",
      headers: { "Authorization": `Bearer ${token}` }
    });

    alert("Account deleted. You will be logged out.");
    window.location.href = "/";
  }

  async function viewDataProcessing() {
    const token = await getToken();
    const response = await fetch("http://localhost:8000/api/user/data-processing-log", {
      headers: { "Authorization": `Bearer ${token}` }
    });
    const data = await response.json();
    console.log(data); // Show in modal or new page
  }

  return (
    <div className="container max-w-4xl py-12">
      <h1>Privacy Settings</h1>

      <section className="my-8">
        <h2>Your Data</h2>
        <button onClick={viewDataProcessing} className="btn-secondary">
          View Data Processing Log
        </button>
        <p className="text-sm text-gray-600">
          See what data we collect and how we use it
        </p>
      </section>

      <section className="my-8">
        <h2>Export Your Data</h2>
        <button onClick={exportData} className="btn-secondary">
          Download All My Data
        </button>
        <p className="text-sm text-gray-600">
          GDPR Right to Portability - Download all your data as JSON
        </p>
      </section>

      <section className="my-8 border-t pt-8">
        <h2 className="text-red-600">Danger Zone</h2>
        <button onClick={deleteAccount} className="btn-danger">
          Delete My Account
        </button>
        <p className="text-sm text-gray-600">
          GDPR Right to Erasure - Permanently delete your account and all data
        </p>
      </section>
    </div>
  );
}
```

---

### 7. Security Settings Page
**File:** `app/(dashboard)/settings/security/page.tsx`

```tsx
"use client";

import { useAuth } from "@clerk/nextjs";
import { useState, useEffect } from "react";

export default function SecuritySettingsPage() {
  const { getToken } = useAuth();
  const [sessions, setSessions] = useState([]);
  const [securityLog, setSecurityLog] = useState([]);

  useEffect(() => {
    loadSessions();
    loadSecurityLog();
  }, []);

  async function loadSessions() {
    const token = await getToken();
    const response = await fetch("http://localhost:8000/api/user/sessions", {
      headers: { "Authorization": `Bearer ${token}` }
    });
    const data = await response.json();
    setSessions(data.sessions);
  }

  async function loadSecurityLog() {
    const token = await getToken();
    const response = await fetch("http://localhost:8000/api/user/security-log", {
      headers: { "Authorization": `Bearer ${token}` }
    });
    const data = await response.json();
    setSecurityLog(data.events);
  }

  async function logoutAllDevices() {
    const confirmed = confirm("Logout from all other devices?");
    if (!confirmed) return;

    const token = await getToken();
    await fetch("http://localhost:8000/api/user/logout-all", {
      method: "POST",
      headers: { "Authorization": `Bearer ${token}` }
    });

    alert("All other sessions have been logged out");
    loadSessions();
  }

  return (
    <div className="container max-w-4xl py-12">
      <h1>Security Settings</h1>

      <section className="my-8">
        <h2>Active Sessions</h2>
        <button onClick={logoutAllDevices} className="btn-danger mb-4">
          Logout All Other Devices
        </button>

        <div className="space-y-2">
          {sessions.map((session, i) => (
            <div key={i} className="border p-4 rounded">
              <div className="flex justify-between">
                <div>
                  <p className="font-medium">{session.device}</p>
                  <p className="text-sm text-gray-600">{session.ip_address}</p>
                </div>
                <div className="text-right">
                  <p className="text-sm">Last seen: {session.last_seen}</p>
                  {session.is_current && (
                    <span className="text-green-600 text-xs">Current Session</span>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="my-8">
        <h2>Security Log</h2>
        <div className="space-y-2">
          {securityLog.map((event, i) => (
            <div key={i} className="border-b py-2 text-sm">
              <div className="flex justify-between">
                <span>{event.event_type} - {event.path}</span>
                <span className={event.status === 'success' ? 'text-green-600' : 'text-red-600'}>
                  {event.status}
                </span>
              </div>
              <div className="text-gray-600 text-xs">
                {event.timestamp} • {event.ip_address}
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
```

---

## 🔗 Update Footer Links

Add legal links to your footer:

```tsx
// components/Footer.tsx
<footer>
  <nav>
    <a href="/legal/privacy-policy">Privacy Policy</a>
    <a href="/legal/terms-of-service">Terms of Service</a>
    <a href="/legal/cookie-policy">Cookie Policy</a>
    <a href="mailto:privacy@reconai.com">Contact Privacy Team</a>
  </nav>
</footer>
```

---

## ✅ Frontend Security Checklist

### Critical (Before Launch)
- [ ] Create privacy policy page
- [ ] Create terms of service page
- [ ] Create cookie policy page
- [ ] Add cookie consent banner
- [ ] Add terms acceptance flow
- [ ] Get legal review ($500-2000)

### Important (Within 30 Days)
- [ ] Create privacy settings page
- [ ] Create security settings page
- [ ] Add footer links to legal pages
- [ ] Test data export functionality
- [ ] Test account deletion
- [ ] Add "Do Not Sell" option (if serving California)

### Nice to Have
- [ ] Two-factor authentication UI (Clerk provides this)
- [ ] Email notifications for security events
- [ ] Suspicious activity alerts

---

## 📊 Time Estimates

- **Privacy policy page:** 2-4 hours (using template)
- **Terms of service page:** 2-4 hours (using template)
- **Cookie policy page:** 1 hour
- **Cookie consent banner:** 30 minutes
- **Terms acceptance flow:** 2 hours
- **Privacy settings page:** 3 hours
- **Security settings page:** 3 hours
- **Legal review:** 1-2 weeks (external)

**Total:** 13-18 hours of development + legal review

---

## 🚨 Common Mistakes to Avoid

1. **Don't skip the privacy policy** - It's required by law in most countries
2. **Don't copy another company's legal docs** - They're copyrighted, and won't match your service
3. **Don't forget cookie consent** - GDPR fines are up to €20 million
4. **Don't store sensitive data in cookies** - Use httpOnly cookies or server sessions
5. **Don't log passwords or tokens** - Never console.log authentication data

---

## 💰 Budget for Legal

### DIY Option (Not Recommended)
- Use Termly/TermsFeed generators: $0-200/year
- Risk: May not be fully compliant
- Best for: MVP/beta testing

### Professional Option (Recommended)
- Lawyer review: $500-2000
- Includes: Privacy policy, terms of service, cookie policy
- Best for: Production launch

### Enterprise Option
- Full legal team: $5000-15000
- Includes: All docs + GDPR/CCPA compliance audit
- Best for: Series A+ or handling sensitive financial data

---

## 📞 Get Help

### Legal Templates
- https://www.termsfeed.com/
- https://www.termly.io/
- https://www.iubenda.com/

### Find a Lawyer
- Upwork (search "privacy policy lawyer")
- https://www.rocketlawyer.com/
- Local law firms (search "tech startup lawyer [your city]")

### GDPR Resources
- Official checklist: https://gdpr.eu/checklist/
- European Commission guide: https://ec.europa.eu/info/law/law-topic/data-protection_en

### CCPA Resources
- California Attorney General: https://oag.ca.gov/privacy/ccpa
- CCPA compliance guide: https://www.termly.io/resources/articles/ccpa-compliance-guide/

---

## ✅ Summary

### Backend (Already Done ✅)
- Rate limiting
- Security headers
- Audit logging
- GDPR endpoints (export, delete, transparency)
- Session management
- Security event logging

### Frontend (Your TODO)
1. **Legal pages** (privacy, terms, cookies)
2. **Cookie consent banner**
3. **Terms acceptance flow**
4. **Privacy settings page**
5. **Security settings page**
6. **Get legal review**

**Estimated time:** 13-18 hours + 1-2 weeks for legal review

---

**Questions?** Check the backend at http://localhost:8000/docs or email the dev team.
