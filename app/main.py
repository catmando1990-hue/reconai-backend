# app/main.py
from __future__ import annotations
import os
import sentry_sdk

# Initialize Sentry for error tracking
sentry_dsn = os.getenv("SENTRY_DSN")
if sentry_dsn:
    sentry_sdk.init(
        dsn=sentry_dsn,
        send_default_pii=True,
        traces_sample_rate=1.0,
        environment=os.getenv("ENVIRONMENT", "development"),
    )

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

# Import all routers that exist
from app.routers.files import router as files_router
from app.routers.exports import router as exports_router
from app.routers.reconai import router as reconai_router
from app.routers.transactions import router as transactions_router
from app.routers.accounting import router as accounting_router
from app.routers.tax import router as tax_router
from app.routers.credit import router as credit_router
from app.routers.feedback import router as feedback_router
from app.routers.plaid import router as plaid_router
from app.routers.bookkeeping import router as bookkeeping_router
from app.routers.auth import router as auth_router
from app.routers.me import router as me_router
from app.routers.readonly import router as readonly_router
from app.routers.signals import router as signals_router
from app.routers.users import router as users_router
from app.routers.vendors import router as vendors_router
from app.routers.bills import router as bills_router
from app.routers.receipts import router as receipts_router
from app.routers.organizations import router as organizations_router
from app.routers.entities import router as entities_router
from app.routers.contact import router as contact_router
from app.routers.newsletter import router as newsletter_router
from app.routers.customers import router as customers_router
from app.routers.invoices import router as invoices_router
from app.routers.reports import router as reports_router
from app.routers.invoicing import router as invoicing_router
from app.routers.bills_ap import router as bills_ap_router
from app.routers.stripe_webhooks import router as stripe_webhooks_router
from app.routers.compliance import router as compliance_router
from app.routers import claude
from app.routers.health import router as health_router, set_startup_time
from app.routers.financial_reports import router as financial_reports_router
from app.routers.tax_intelligence import router as tax_intelligence_router
from app.routers.mvp import router as mvp_router
from app.routers.intelligence import router as intelligence_router
from app.routers.cfo import router as cfo_router
from app.routers.audit import router as audit_router
from app.routers.policy import router as policy_router
from app.routers.evidence import router as evidence_router
from app.routers.onboarding import router as onboarding_router
from app.routers.rbac import router as rbac_router
from app.routers.retention import router as retention_router
from app.routers.export_pack import router as export_pack_router
from app.routers.status import router as status_router
from app.routers.support import router as support_router
from app.routers.deploy_runs import router as deploy_runs_router
from app.routers.system_state import router as system_state_router
from app.routers.governance import router as governance_router
from app.routers.plaid_hardening import router as plaid_hardening_router
# Production Plaid API (auth-protected, org-scoped, encrypted tokens)
from app.routers.plaid_v2 import router as plaid_v2_router
from app.routers.transaction_overrides import router as transaction_overrides_router
from app.routers.audit_api import router as audit_api_router
from app.routers.policy_api import router as policy_api_router
from app.routers.maintenance_api import router as maintenance_api_router
from app.routers.system_status_api import router as system_status_api_router
from app.routers.release_hardening_api import router as release_hardening_api_router
from app.routers.intelligence_guardrails_api import router as intelligence_guardrails_api_router
from app.routers.me_claims import router as me_claims_router
from app.routers.intelligence_categorization_api import router as intelligence_categorization_router
from app.routers.intelligence_duplicates_api import router as intelligence_duplicates_router
from app.routers.intelligence_cashflow_api import router as intelligence_cashflow_router
from app.routers.intelligence_status_api import router as intelligence_status_router
from app.routers.intelligence_export_api import router as intelligence_export_router
from app.routers.signals_prioritization_api import router as signals_prioritization_router
from app.routers.entitlements_api import router as entitlements_router
from app.routers.admin_actions_api import router as admin_actions_router
from app.routers.admin_diagnostics_api import router as admin_diagnostics_router
from app.routers.billing_api import router as billing_api_router
from app.routers.billing_status_api import router as billing_status_api_router
from app.routers.billing_sync_api import router as billing_sync_api_router
from app.routers.billing_safeguards_api import router as billing_safeguards_api_router
from app.routers.billing_invoices_api import router as billing_invoices_api_router
from app.routers.billing_role_management_api import router as billing_role_management_api_router
from app.routers.billing_invoice_export_api import router as billing_invoice_export_api_router
from app.routers.billing_governance_ui_support import router as billing_governance_ui_router
from app.routers.billing_financial_controls_api import router as billing_financial_controls_router
from app.routers.billing_data_retention_api import router as billing_data_retention_router
from app.routers.billing_erp_exports_api import router as billing_erp_exports_router
from app.routers.investor_reporting_api import router as investor_reporting_router
from app.routers.compliance_automation_api import router as compliance_automation_router
from app.routers.security_trust_api import router as security_trust_router
from app.routers.ai_financial_intelligence_api import router as ai_financial_intelligence_router
from app.routers.gtm_pricing_api import router as gtm_pricing_router
from app.routers.production_readiness_api import router as production_readiness_router
from app.routers.ml_governance_api import router as ml_governance_router
from app.routers.onboarding_api import router as onboarding_api_router
from app.routers.capabilities_api import router as capabilities_router
from app.routers.activation_metrics_api import router as activation_metrics_router
from app.routers.investor_export_api import router as investor_export_router
from app.routers.activation_benchmarks_api import router as activation_benchmarks_router
from app.routers.investor_audit_api import router as investor_audit_router
from app.routers.org_governance_api import router as org_governance_router
from app.routers.funnel_attribution_api import router as funnel_attribution_router
from app.routers.killswitch_api import router as killswitch_router
from app.routers.billing_reconcile_api import router as billing_reconcile_router
from app.routers.platform_hardening_api import router as platform_hardening_router
# STEP A — AI-Powered Diagnostics API (Admin-Only, Manual-Run)
from app.routers.diagnostics_api import router as diagnostics_router
# GOVCON — DCAA-Compliant Government Contracting Modules
from app.routers.govcon_contracts import router as govcon_contracts_router
from app.routers.govcon_timekeeping import router as govcon_timekeeping_router
from app.routers.govcon_indirects import router as govcon_indirects_router
from app.routers.govcon_reconciliation import router as govcon_reconciliation_router
from app.routers.govcon_audit import router as govcon_audit_router
# GOVCON — Export API (Manual-Run, Read-Only)
from app.routers.govcon_export_api import router as govcon_export_router
# GOVCON — PDF Export API (Manual-Run, Read-Only)
from app.routers.govcon_export_pdf_api import router as govcon_export_pdf_router
# GOVCON — Evidence Viewer API (Read-Only, Fail-Closed)
from app.routers.govcon_evidence_api import router as govcon_evidence_router
# GOVCON — Audit Verification API (Read-Only, Fail-Closed)
from app.routers.govcon_audit_verify_api import router as govcon_audit_verify_router
# DASHBOARD — Main Dashboard Overview API
from app.routers.dashboard_overview import router as dashboard_overview_router
# DASHBOARD — Metrics API (Chart data, safe defaults)
from app.routers.dashboard_metrics_api import router as dashboard_metrics_router
# PHASE 3B — AR Aging API (Read-Only, Manual-Refresh)
from app.routers.ar_aging import router as ar_aging_router
# PHASE 1 — Transaction Intelligence (Read-Only Overlay)
from app.routers.intelligence_classify_api import router as intelligence_classify_router
# PHASE 2 — GovCon/DCAA Compliance Pipeline (Read-Only Overlay)
from app.routers.govcon_compliance_api import router as govcon_compliance_router
# PHASE 3 — CFO / Financial Controls (Read-Only)
from app.routers.cfo_controls_api import router as cfo_controls_router


def get_allowed_origins() -> list[str]:
    env = os.getenv("CORS_ORIGINS", "").strip()
    if env:
        return [o.strip() for o in env.split(",") if o.strip()]
    return [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://localhost:1420",
        "http://127.0.0.1:1420",
        "tauri://localhost",
        "https://tauri.localhost",
        "https://reconai-frontend.onrender.com",
        "https://reconai-frontend.vercel.app",
        "https://reconaitechnology.com",
        "https://www.reconaitechnology.com",
    ]


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        if os.getenv("ENVIRONMENT") == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        return response


app = FastAPI(
    title="ReconAI Backend",
    version="0.1.0",
    description="Financial Intelligence API for ReconAI"
)

# BUILD 14 — Register structured error handlers BEFORE router mounts
from app.middleware.error_envelope import register_error_handlers
register_error_handlers(app)

from app.middleware import AuthContextMiddleware, RateLimitMiddleware
from app.middleware.body_size_limit import BodySizeLimitMiddleware
from app.middleware.request_id import RequestIdMiddleware
from app.middleware.incident_guard import IncidentGuardMiddleware

# Phase-1 Hotfix: Middleware ordering corrected
# In Starlette/FastAPI, LAST added middleware executes FIRST.
# RequestIdMiddleware must be added LAST to guarantee it runs FIRST on request
# and LAST on response, ensuring x-request-id is always present.
app.add_middleware(AuthContextMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(IncidentGuardMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
# BUILD 14 — Request body size limit (1MB default, includes request_id in errors)
app.add_middleware(BodySizeLimitMiddleware, max_bytes=1_000_000)

if os.getenv("ENVIRONMENT") == "production":
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=[
            "reconai-backend.onrender.com",
            "api.reconai.com",
            "*.vercel.app"
        ]
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_origin_regex=r"^https://.*\.vercel\.app$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH", "HEAD"],
    allow_headers=["*"],
    expose_headers=[],
    max_age=3600,
)

# Phase-1 Hotfix: RequestIdMiddleware added LAST (executes FIRST)
# Guarantees x-request-id on ALL responses including errors and OPTIONS
app.add_middleware(RequestIdMiddleware)


@app.api_route("/", methods=["GET", "HEAD"])
def root():
    return {
        "status": "ok",
        "service": "reconai-backend",
        "version": "1.0.0"
    }


# Health endpoint moved to health_router


from app.routers.plaid import classify_transactions

app.add_api_route(
    "/classify-transactions",
    classify_transactions,
    methods=["POST"],
    tags=["classification"]
)

app.include_router(auth_router)
app.include_router(me_router)
app.include_router(readonly_router)
app.include_router(signals_router)
app.include_router(users_router)
app.include_router(vendors_router)
app.include_router(bills_router)
app.include_router(receipts_router)
app.include_router(organizations_router)
app.include_router(entities_router)
app.include_router(contact_router)
app.include_router(newsletter_router)
app.include_router(customers_router)
app.include_router(invoices_router)
app.include_router(invoicing_router)
app.include_router(bills_ap_router)
app.include_router(reports_router)
app.include_router(stripe_webhooks_router)
app.include_router(compliance_router)
app.include_router(files_router)
app.include_router(exports_router)
app.include_router(reconai_router)
app.include_router(transactions_router)
app.include_router(accounting_router)
app.include_router(tax_router)
app.include_router(credit_router)
app.include_router(feedback_router)
app.include_router(mvp_router)  # Load before plaid_router to avoid /transactions route conflict
app.include_router(plaid_router)
app.include_router(bookkeeping_router)
app.include_router(financial_reports_router)
app.include_router(tax_intelligence_router)
app.include_router(claude.router)
app.include_router(health_router, prefix="/health")
app.include_router(intelligence_router, prefix="/intelligence")
app.include_router(cfo_router, prefix="/cfo")
app.include_router(audit_router)
app.include_router(policy_router)
app.include_router(evidence_router)
app.include_router(onboarding_router)
app.include_router(rbac_router)
app.include_router(retention_router)
app.include_router(export_pack_router)
app.include_router(status_router)
app.include_router(support_router)
app.include_router(deploy_runs_router)
app.include_router(system_state_router)
app.include_router(governance_router)

# BUILD 3C/3D — Plaid Ingestion Hardening
app.include_router(plaid_hardening_router)
# Production Plaid API (auth-protected, org-scoped, encrypted tokens, cursor-based sync)
app.include_router(plaid_v2_router)
# BUILD 4 — Controlled Write Enablement
app.include_router(transaction_overrides_router)
# BUILD 5 — Audit Log + Compliance Surface (Read-Only)
app.include_router(audit_api_router)
# BUILD 6 — Policy & Disclaimer Enforcement
app.include_router(policy_api_router)
# BUILD 7 + BUILD 10 — Admin Maintenance Kill Switch + Extended Status
app.include_router(maintenance_api_router)
# BUILD 11 — System Health Status
app.include_router(system_status_api_router)
# BUILD 12 — Release Hardening (Structured Errors)
app.include_router(release_hardening_api_router)
# BUILD 13 — Intelligence Guardrails (Advisory Mode)
app.include_router(intelligence_guardrails_api_router)
# BUILD 15 — Claims debug endpoint
app.include_router(me_claims_router)
# INTELLIGENCE v1 — Advisory-only intelligence endpoints
app.include_router(intelligence_categorization_router)  # 1A: Categorization suggestions
app.include_router(intelligence_duplicates_router)      # 1B: Duplicate detection
app.include_router(intelligence_cashflow_router)        # 1C: Cashflow insights
# BUILD 28-30 — Intelligence Status (Settings Page)
app.include_router(intelligence_status_router)
# BUILD 28-30 — Admin Actions API (Diagnostics & Fixes with Approval Flow)
app.include_router(admin_actions_router)
# PHASE 5: Admin Diagnostics with JSON Envelope Hardening
app.include_router(admin_diagnostics_router)
# STEP 4B — Evidence Retention & Manual Exports
app.include_router(intelligence_export_router)
# STEP 4C — Signals Prioritization (Deterministic Ranking)
app.include_router(signals_prioritization_router)
# STEP 5 — Entitlements API (Tier Limits)
app.include_router(entitlements_router)
# STEP 8 — Billing API (Stripe Checkout)
app.include_router(billing_api_router)
# STEP 8 — Billing Status API (Read-Only)
app.include_router(billing_status_api_router)
# STEP 8 — Billing Sync API (Manual Reconciliation)
app.include_router(billing_sync_api_router)
# STEP 8 — Billing Safeguards API (Cancel/Downgrade)
app.include_router(billing_safeguards_api_router)
# STEP 9 — Billing Invoices API (Read-Only, Stripe)
app.include_router(billing_invoices_api_router)
# STEP 10 — Billing Role Management API (Manual)
app.include_router(billing_role_management_api_router)
# STEP 10 — Billing Invoice Export API (Manual)
app.include_router(billing_invoice_export_api_router)
# STEP 11 — Billing Governance UI Support (Read-Only)
app.include_router(billing_governance_ui_router)
# STEP 11 — Billing Financial Controls API (Soft Limits, Alerts)
app.include_router(billing_financial_controls_router)
# STEP 11 — Billing Data Retention API (Export/Delete with Audit Seal)
app.include_router(billing_data_retention_router)
# STEP 11 — Billing ERP Exports API (Manual, CSV)
app.include_router(billing_erp_exports_router)
# STEP 12 — Investor Reporting API (Read-Only)
app.include_router(investor_reporting_router)
# STEP 12 — Compliance Automation API (Read-Only)
app.include_router(compliance_automation_router)
# STEP 12 — Security & Trust API (Read-Only)
app.include_router(security_trust_router)
# STEP 12 — AI Financial Intelligence API (Read-Only)
app.include_router(ai_financial_intelligence_router)
# STEP 13 — GTM & Pricing API (Read-Only)
app.include_router(gtm_pricing_router)
# STEP 13 — Production Readiness API (Read-Only)
app.include_router(production_readiness_router)
# STEP 13 — ML Governance API (Read-Only)
app.include_router(ml_governance_router)
# STEP 13 — Onboarding API (Manual)
app.include_router(onboarding_api_router)
# STEP 14A — Capability Gating API (Read-Only)
app.include_router(capabilities_router)
# STEP 14B — Activation Metrics API (Read-Only)
app.include_router(activation_metrics_router)
# STEP 16 — Investor Export API (Read-Only)
app.include_router(investor_export_router)
# STEP 17 — Activation Benchmarks API (Read-Only)
app.include_router(activation_benchmarks_router)
# STEP 21 — Investor Audit Trail & Export Receipts (Read-Only)
app.include_router(investor_audit_router)
# STEP 22 — Org-Level Governance Dashboard (Read-Only)
app.include_router(org_governance_router)
# STEP 23 — Activation → Revenue Funnel Attribution (Read-Only)
app.include_router(funnel_attribution_router)
# STEP 24 — Kill-Switch Status API (Read-Only)
app.include_router(killswitch_router)
# STEP 25 — Billing Reconciliation API (Read-Only)
app.include_router(billing_reconcile_router)
# STEP 26 — Platform Hardening API (Read-Only)
app.include_router(platform_hardening_router)
# STEP A — AI-Powered Diagnostics API (Admin-Only, Manual-Run, Confirmation Phrases)
app.include_router(diagnostics_router)
# GOVCON — DCAA-Compliant Government Contracting (GovCon/Enterprise tiers only)
app.include_router(govcon_contracts_router)
app.include_router(govcon_timekeeping_router)
app.include_router(govcon_indirects_router)
app.include_router(govcon_reconciliation_router)
app.include_router(govcon_audit_router)
# GOVCON — Export API (Manual-Run, Read-Only, Audit-Logged)
app.include_router(govcon_export_router)
# GOVCON — PDF Export API (Manual-Run, Read-Only, Audit-Logged)
app.include_router(govcon_export_pdf_router)
# GOVCON — Evidence Viewer API (Read-Only, Fail-Closed)
app.include_router(govcon_evidence_router)
# GOVCON — Audit Verification API (Read-Only, Fail-Closed)
app.include_router(govcon_audit_verify_router)
# DASHBOARD — Main Dashboard Overview API (Read-Only, Manual-Refresh)
app.include_router(dashboard_overview_router)
# DASHBOARD — Metrics API (Chart Data, Safe Defaults)
app.include_router(dashboard_metrics_router)
# PHASE 3B — AR Aging API (Read-Only, Manual-Refresh)
app.include_router(ar_aging_router)
# PHASE 1 — Transaction Intelligence (Read-Only Overlay, Manual-Run)
app.include_router(intelligence_classify_router)
# PHASE 2 — GovCon/DCAA Compliance Pipeline (Read-Only Overlay, Manual-Run)
app.include_router(govcon_compliance_router)
# PHASE 3 — CFO / Financial Controls (Read-Only, Manual-Refresh)
app.include_router(cfo_controls_router)


@app.on_event("startup")
async def startup_event():
    from app.db import init_db
    from app.bookkeeping.engine import BookkeeperEngine
    from app.invoicing.engine import InvoicingEngine
    from app.bills.engine import BillsEngine
    from app.financial_reports.engine import FinancialReportsEngine
    from app.tax_intelligence.engine import TaxIntelligenceEngine
    from app.routers.invoicing import set_invoicing_engine
    from app.routers.bills_ap import set_bills_engine
    from app.routers.financial_reports import set_reports_engine
    from app.routers.tax_intelligence import set_tax_engine
    from app.db import DB_PATH

    print(">> ReconAI Backend starting up...")
    print(">> Initializing database...")
    await run_in_threadpool(init_db)
    print(">> Database ready")

    # Step 15: Enforce approved run guardrail in production
    from app.guardrails import enforce_approved_run
    await run_in_threadpool(enforce_approved_run)

    # STEP 8: Enforce Stripe secrets in production (fail-closed)
    from app.guardrails.stripe_hardening import enforce_stripe_prod
    await run_in_threadpool(enforce_stripe_prod)

    # Enforce Plaid OAuth secrets in production (fail-closed)
    from app.guardrails.plaid_oauth_hardening import enforce_plaid_oauth_prod, warn_plaid_redirect_uri
    await run_in_threadpool(enforce_plaid_oauth_prod)
    await run_in_threadpool(warn_plaid_redirect_uri)

    print(">> Initializing bookkeeping engine...")
    bookkeeper = await run_in_threadpool(lambda: BookkeeperEngine(DB_PATH))
    print(">> Bookkeeping engine ready")

    print(">> Initializing invoicing engine...")
    invoicing = await run_in_threadpool(lambda: InvoicingEngine(DB_PATH, bookkeeper_engine=bookkeeper))
    set_invoicing_engine(invoicing)
    print(">> Invoicing engine ready")

    print(">> Initializing bills & AP engine...")
    bills = await run_in_threadpool(lambda: BillsEngine(DB_PATH, bookkeeper_engine=bookkeeper))
    set_bills_engine(bills)
    print(">> Bills & AP engine ready")

    print(">> Initializing financial reports engine...")
    reports = await run_in_threadpool(lambda: FinancialReportsEngine(bookkeeper_engine=bookkeeper))
    set_reports_engine(reports)
    print(">> Financial reports engine ready")

    print(">> Initializing tax intelligence engine...")
    tax = await run_in_threadpool(lambda: TaxIntelligenceEngine(reports_engine=reports))
    set_tax_engine(tax)
    print(">> Tax intelligence engine ready")

    print(f">> CORS enabled for: {get_allowed_origins()}")
    print(f">> CORS regex: ^https://.*\\.vercel\\.app$")
    print(">> Classify endpoint mounted at: /classify-transactions")
    print(">> Bookkeeping API mounted at: /api/bookkeeping")
    print(">> Invoicing API mounted at: /api/invoicing")
    print(">> Bills & AP API mounted at: /api/bills")
    print(">> Financial Reports API mounted at: /api/financial-reports")
    print(">> Tax Intelligence API mounted at: /api/tax-intelligence")
    print(">> Plaid Hardening API mounted at: /api/plaid (BUILD 3C/3D - sync disabled by default)")
    print(">> Transaction Overrides API mounted at: /api/transactions/:id/override (BUILD 4 - writes disabled by default)")
    print(">> Audit API mounted at: /api/audit (BUILD 5 - read-only)")
    print(">> Policy API mounted at: /api/policy (BUILD 6 - acknowledgements audit-logged)")
    print(">> Maintenance API mounted at: /api/admin/maintenance (BUILD 7+10 - admin-only, extended status)")
    print(">> System Status API mounted at: /api/system/status (BUILD 11 - read-only health)")
    print(">> Release Hardening API mounted at: /api/hardening/config (BUILD 12 - structured errors)")
    print(">> Intelligence Guardrails API mounted at: /api/intelligence/guardrails (BUILD 13 - advisory mode)")
    print(">> BUILD 14: Enforcement consistency (request_id in all errors, x-request-id header)")
    print(">> BUILD 15: Claims debug at /api/me/claims, require_admin helper available")
    print(">> BUILD 16: Plaid idempotency helpers ready (tx_identity_key)")
    print(">> INTELLIGENCE v1: Advisory-only endpoints active (categorization, duplicates, cashflow)")
    print(">> BUILD 28-30: Admin Actions API at /api/admin (diagnostics, fixes with approval flow)")
    print(">> STEP 8: Billing API at /api/billing/create-checkout-session (Stripe Checkout)")
    print(">> STEP 8: Billing Status API at /api/billing/status (read-only)")
    print(">> STEP 8: Billing Sync API at /api/billing/sync (manual reconciliation)")
    print(">> STEP 8: Billing Safeguards at /api/billing/cancel, /api/billing/downgrade (scheduled, not immediate)")
    print(">> STEP 8: Stripe prod hardening enforced (fail-closed if secrets missing)")
    print(">> STEP 9: Billing Invoices API at /api/billing/invoices (read-only, Stripe source)")
    print(">> STEP 9: Enterprise RBAC enforced on all billing endpoints")
    print(">> STEP 10: Billing Role Management at /api/billing/roles (manual, owner/billing_admin)")
    print(">> STEP 10: Invoice Export at /api/billing/invoices/export (manual, read-only)")
    print(">> STEP 10: Stripe linkage validation enforced")
    print(">> STEP 11: Governance UI Support at /api/billing/governance (read-only filters, diffs, export history)")
    print(">> STEP 11: Financial Controls at /api/billing/controls (soft limits, approval thresholds, alerts)")
    print(">> STEP 11: Data Retention at /api/billing/retention (right-to-export, right-to-delete, audit sealed)")
    print(">> STEP 11: ERP Exports at /api/billing/erp (NetSuite/QuickBooks CSV, manual trigger only)")
    print(">> STEP 12: Investor Reporting at /api/investor (GAAP summaries, board-ready exports, read-only)")
    print(">> STEP 12: Compliance Automation at /api/compliance (DCAA, SF-1408, gap analysis, read-only)")
    print(">> STEP 12: Security & Trust at /api/security (SOC 2 tracker, evidence vault, trust artifacts)")
    print(">> STEP 12: AI Financial Intelligence at /api/ai (NL queries, insights, forecasting, read-only)")
    print(">> STEP 13: GTM Pricing at /api/gtm (tiers, features, upgrade paths, demo metadata)")
    print(">> STEP 13: Production Readiness at /api/production (SLOs, error budgets, runbooks, load tests)")
    print(">> STEP 13: ML Governance at /api/ml (models, evaluations, drift, prompts)")
    print(">> STEP 13: Onboarding at /api/onboarding (setup, checklists, sample data, first-run insights)")
    print(">> STEP 14A: Capabilities at /api/entitlements/capabilities (central tier, features, limits)")
    print(">> STEP 14B: Activation Metrics at /api/metrics/activation (time-to-first-value, read-only)")
    print(">> STEP 16: Investor Export at /api/investor/export (JSON/PDF snapshots, read-only)")
    print(">> STEP 17: Activation Benchmarks at /api/benchmarks (percentiles, cohorts, read-only)")
    print(">> STEP 18: Investor Export Hardening (allowlist, PII redaction, rate limits, watermark)")
    print(">> STEP 19: Benchmark Quality Controls (min cohort size, insufficient_data states)")
    print(">> STEP 20: Upgrade UX Wiring (manual navigation to Stripe upgrade flow)")
    print(">> STEP 21: Investor Audit at /api/investor/audit (receipts, export trail, integrity hashes)")
    print(">> STEP 22: Org Governance at /api/org/governance (compliance, access controls, data policies)")
    print(">> STEP 23: Funnel Attribution at /api/funnel (activation→revenue, conversion rates, attribution)")
    print(">> STEP 24: Kill-Switch at /api/killswitch (feature toggles, fail-closed enforcement)")
    print(">> STEP 25: Billing Reconcile at /api/billing/reconcile (billing↔entitlement drift detection)")
    print(">> STEP 26: Platform Hardening at /api/platform/hardening (rate limits, size caps, timeouts)")
    print(">> STEP A: Diagnostics API at /api/diagnostics (admin-only, manual-run, confirmation phrases, 5/min/org)")
    print(">> GOVCON: Contracts API at /govcon/contracts (DCAA-compliant, advisory-only)")
    print(">> GOVCON: Timekeeping API at /govcon/timekeeping (labor tracking, corrections require evidence)")
    print(">> GOVCON: Indirects API at /govcon/indirects (pools, rates, allowability per FAR 31.201)")
    print(">> GOVCON: Reconciliation API at /govcon/reconciliation (ICS, SF-1408, variance analysis)")
    print(">> GOVCON: Audit API at /govcon/audit (immutable trail, hash chain integrity, 6-year retention)")
    print(">> DASHBOARD: Overview API at /api/dashboard/overview (CFO snapshot, read-only, manual-refresh)")
    print(">> PHASE 3B: AR Aging API at /api/ar/aging (buckets, read-only, manual-refresh)")
    print(">> PHASE 1: Transaction Intelligence at /api/intelligence/classify, /api/intelligence/transactions (manual-run, read-only overlay)")
    print(">> PHASE 2: GovCon/DCAA Compliance at /api/govcon/transactions, /api/govcon/export (manual-run, FAR 31.201, CAS 418)")
    print(">> PHASE 3: CFO Controls at /api/cfo/overview, /api/cfo/forecast, /api/cfo/exceptions (read-only, projections≠facts)")
    set_startup_time()
    print(">> Sentry initialized" if os.getenv("SENTRY_DSN") else ">> WARNING: Sentry not configured")


@app.on_event("shutdown")
async def shutdown_event():
    print("ReconAI Backend shutting down...")


