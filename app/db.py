# app/db.py

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

# Portable data folder (Render persistent disk)
# On Render, the disk is mounted at /var/data (absolute path, not relative to project)
# Locally, defaults to ./data
_DEFAULT_DATA_DIR = "/var/data" if os.path.exists("/var/data") else "./data"
DATA_DIR = Path(os.getenv("DATA_DIR", _DEFAULT_DATA_DIR))
DATA_DIR.mkdir(parents=True, exist_ok=True)

UPLOADS_DIR = Path(os.getenv("UPLOADS_DIR", str(DATA_DIR / "uploads")))
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = Path(os.getenv("DB_PATH", str(DATA_DIR / "reconai.db")))


def get_db_connection():
    """Get SQLite database connection"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Initialize database with multi-tenancy support"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(DB_PATH) as conn:
        # =================================================================
        # MULTI-TENANCY CORE TABLES
        # =================================================================

        # Organizations (Tenants)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS organizations (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                slug TEXT UNIQUE NOT NULL,
                tier TEXT NOT NULL DEFAULT 'individual',
                industry TEXT,
                subscription_status TEXT DEFAULT 'trial',
                trial_ends_at TEXT,
                subscription_ends_at TEXT,
                stripe_customer_id TEXT UNIQUE,
                stripe_subscription_id TEXT,
                features TEXT DEFAULT '{}',
                branding TEXT DEFAULT '{}',
                owner_user_id TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)

        # Users
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT,
                first_name TEXT,
                last_name TEXT,
                full_name TEXT,
                company_name TEXT,
                phone TEXT,
                avatar_url TEXT,
                address TEXT,
                city TEXT,
                state TEXT,
                zip_code TEXT,
                country TEXT DEFAULT 'USA',
                timezone TEXT DEFAULT 'America/New_York',
                default_org_id TEXT,
                is_active INTEGER DEFAULT 1,
                email_verified INTEGER DEFAULT 0,
                profile_completed INTEGER DEFAULT 0,
                email_notifications INTEGER DEFAULT 1,
                transaction_alerts INTEGER DEFAULT 1,
                compliance_alerts INTEGER DEFAULT 1,
                invoice_reminders INTEGER DEFAULT 1,
                weekly_summary INTEGER DEFAULT 1,
                monthly_report INTEGER DEFAULT 1,
                last_login_at TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (default_org_id) REFERENCES organizations(id)
            )
        """)

        # P0: Migration - Add profile_completed column if missing
        try:
            conn.execute("ALTER TABLE users ADD COLUMN profile_completed INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # Column already exists

        # Organization Members
        conn.execute("""
            CREATE TABLE IF NOT EXISTS organization_members (
                id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'viewer',
                permissions TEXT DEFAULT '{}',
                invited_by TEXT,
                invited_at TEXT,
                joined_at TEXT DEFAULT (datetime('now')),
                is_active INTEGER DEFAULT 1,
                FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (invited_by) REFERENCES users(id),
                UNIQUE(organization_id, user_id)
            )
        """)

        # Entities
        conn.execute("""
            CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                name TEXT NOT NULL,
                legal_name TEXT,
                ein TEXT,
                entity_type TEXT,
                industry TEXT,
                address_line1 TEXT,
                address_line2 TEXT,
                city TEXT,
                state TEXT,
                zip TEXT,
                country TEXT DEFAULT 'US',
                phone TEXT,
                email TEXT,
                website TEXT,
                fiscal_year_end TEXT,
                default_currency TEXT DEFAULT 'USD',
                timezone TEXT DEFAULT 'America/New_York',
                is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
                UNIQUE(organization_id, name)
            )
        """)

        # Dimensions
        conn.execute("""
            CREATE TABLE IF NOT EXISTS dimensions (
                id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                entity_id TEXT,
                dimension_type TEXT NOT NULL,
                name TEXT NOT NULL,
                code TEXT,
                description TEXT,
                parent_id TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
                FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE,
                FOREIGN KEY (parent_id) REFERENCES dimensions(id),
                UNIQUE(organization_id, entity_id, dimension_type, name)
            )
        """)

        # Custom Fields
        conn.execute("""
            CREATE TABLE IF NOT EXISTS custom_fields (
                id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                field_name TEXT NOT NULL,
                field_type TEXT NOT NULL,
                field_options TEXT,
                is_required INTEGER DEFAULT 0,
                default_value TEXT,
                display_order INTEGER DEFAULT 0,
                help_text TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
                UNIQUE(organization_id, entity_type, field_name)
            )
        """)

        # Custom Field Values
        conn.execute("""
            CREATE TABLE IF NOT EXISTS custom_field_values (
                id TEXT PRIMARY KEY,
                custom_field_id TEXT NOT NULL,
                record_id TEXT NOT NULL,
                value TEXT,
                FOREIGN KEY (custom_field_id) REFERENCES custom_fields(id) ON DELETE CASCADE,
                UNIQUE(custom_field_id, record_id)
            )
        """)

        # Approval Rules
        conn.execute("""
            CREATE TABLE IF NOT EXISTS approval_rules (
                id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                entity_id TEXT,
                transaction_type TEXT NOT NULL,
                condition TEXT,
                requires_approval_from TEXT NOT NULL,
                approval_order INTEGER DEFAULT 1,
                is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
                FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE
            )
        """)

        # Approvals
        conn.execute("""
            CREATE TABLE IF NOT EXISTS approvals (
                id TEXT PRIMARY KEY,
                transaction_id TEXT NOT NULL,
                transaction_type TEXT NOT NULL,
                required_approver_id TEXT NOT NULL,
                approved_by TEXT,
                approved_at TEXT,
                status TEXT DEFAULT 'pending',
                notes TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (required_approver_id) REFERENCES users(id),
                FOREIGN KEY (approved_by) REFERENCES users(id)
            )
        """)

        # Create indexes
        conn.execute("CREATE INDEX IF NOT EXISTS idx_orgs_slug ON organizations(slug)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_orgs_tier ON organizations(tier)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_members_org ON organization_members(organization_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_members_user ON organization_members(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_org ON entities(organization_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_dimensions_org ON dimensions(organization_id)")

        # =================================================================
        # MVP TABLES (Phases 010–012)
        # =================================================================

        conn.execute("""
            CREATE TABLE IF NOT EXISTS mvp_uploads (
                id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                filename TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS mvp_transactions (
                id TEXT PRIMARY KEY,
                upload_id TEXT NOT NULL,
                organization_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                tx_date TEXT,
                amount REAL NOT NULL,
                description TEXT NOT NULL,
                merchant TEXT,
                original_category TEXT,
                classification TEXT,
                reason TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (upload_id) REFERENCES mvp_uploads(id) ON DELETE CASCADE,
                FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        conn.execute("CREATE INDEX IF NOT EXISTS idx_mvp_tx_org ON mvp_transactions(organization_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mvp_tx_upload ON mvp_transactions(upload_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mvp_uploads_org ON mvp_uploads(organization_id)")

        # =================================================================
        # LEGACY TABLES (updated for multi-tenancy)
        # =================================================================

        # tokens
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_tokens (
                user_id TEXT PRIMARY KEY,
                access_token TEXT NOT NULL,
                item_id TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)

        # merchant feedback
        conn.execute("""
            CREATE TABLE IF NOT EXISTS merchant_feedback (
                merchant_key TEXT PRIMARY KEY,
                correct_label TEXT NOT NULL,
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)

        # tx feedback
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transaction_feedback (
                tx_id TEXT PRIMARY KEY,
                correct_label TEXT NOT NULL,
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)

        # uploads metadata
        conn.execute("""
            CREATE TABLE IF NOT EXISTS uploads (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                content_type TEXT,
                stored_path TEXT NOT NULL,
                size_bytes INTEGER,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)

        # Contact form submissions
        conn.execute("""
            CREATE TABLE IF NOT EXISTS contact_submissions (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                subject TEXT,
                message TEXT NOT NULL,
                phone TEXT,
                company TEXT,
                source TEXT DEFAULT 'website',
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)

        # Newsletter subscribers
        conn.execute("""
            CREATE TABLE IF NOT EXISTS newsletter_subscribers (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL,
                name TEXT,
                source TEXT DEFAULT 'website',
                list_type TEXT DEFAULT 'general',
                subscribed_at TEXT DEFAULT (datetime('now')),
                unsubscribed_at TEXT,
                resubscribed_at TEXT,
                UNIQUE(email, list_type)
            )
        """)

        # Create indexes for marketing tables
        conn.execute("CREATE INDEX IF NOT EXISTS idx_contact_email ON contact_submissions(email)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_contact_created ON contact_submissions(created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_newsletter_email ON newsletter_subscribers(email)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_newsletter_active ON newsletter_subscribers(unsubscribed_at)")

        # =================================================================
        # INVOICING & CUSTOMERS
        # =================================================================

        # Customers, Invoices, Invoice Items, and Payments tables now created by InvoicingEngine
        # Commented out to avoid conflict with the new AR system
        # conn.execute("""
        #     CREATE TABLE IF NOT EXISTS customers (
        #         id TEXT PRIMARY KEY,
        #         organization_id TEXT NOT NULL,
        #         entity_id TEXT,
        #         name TEXT NOT NULL,
        #         email TEXT,
        #         phone TEXT,
        #         address_line1 TEXT,
        #         address_line2 TEXT,
        #         city TEXT,
        #         state TEXT,
        #         zip TEXT,
        #         country TEXT DEFAULT 'US',
        #         company_name TEXT,
        #         tax_id TEXT,
        #         payment_terms INTEGER DEFAULT 30,
        #         outstanding_balance REAL DEFAULT 0.0,
        #         is_active INTEGER DEFAULT 1,
        #         notes TEXT,
        #         created_at TEXT DEFAULT (datetime('now')),
        #         updated_at TEXT DEFAULT (datetime('now')),
        #         FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
        #         FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE SET NULL
        #     )
        # """)

        # conn.execute("""
        #     CREATE TABLE IF NOT EXISTS invoices (
        #         id TEXT PRIMARY KEY,
        #         organization_id TEXT NOT NULL,
        #         entity_id TEXT,
        #         customer_id TEXT NOT NULL,
        #         invoice_number TEXT NOT NULL,
        #         issue_date TEXT NOT NULL,
        #         due_date TEXT NOT NULL,
        #         status TEXT DEFAULT 'draft',
        #         subtotal REAL NOT NULL DEFAULT 0.0,
        #         tax_rate REAL DEFAULT 0.0,
        #         tax_amount REAL DEFAULT 0.0,
        #         discount_amount REAL DEFAULT 0.0,
        #         total_amount REAL NOT NULL DEFAULT 0.0,
        #         amount_paid REAL DEFAULT 0.0,
        #         currency TEXT DEFAULT 'USD',
        #         notes TEXT,
        #         terms TEXT,
        #         footer TEXT,
        #         sent_at TEXT,
        #         paid_at TEXT,
        #         created_at TEXT DEFAULT (datetime('now')),
        #         updated_at TEXT DEFAULT (datetime('now')),
        #         FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
        #         FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE SET NULL,
        #         FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE RESTRICT,
        #         UNIQUE(organization_id, invoice_number)
        #     )
        # """)

        # conn.execute("""
        #     CREATE TABLE IF NOT EXISTS invoice_items (
        #         id TEXT PRIMARY KEY,
        #         invoice_id TEXT NOT NULL,
        #         description TEXT NOT NULL,
        #         quantity REAL NOT NULL DEFAULT 1,
        #         unit_price REAL NOT NULL DEFAULT 0.0,
        #         amount REAL NOT NULL DEFAULT 0.0,
        #         account_id TEXT,
        #         sort_order INTEGER DEFAULT 0,
        #         FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE
        #     )
        # """)

        # conn.execute("""
        #     CREATE TABLE IF NOT EXISTS payments (
        #         id TEXT PRIMARY KEY,
        #         organization_id TEXT NOT NULL,
        #         entity_id TEXT,
        #         customer_id TEXT NOT NULL,
        #         invoice_id TEXT,
        #         payment_date TEXT NOT NULL,
        #         amount REAL NOT NULL,
        #         payment_method TEXT,
        #         reference_number TEXT,
        #         notes TEXT,
        #         created_at TEXT DEFAULT (datetime('now')),
        #         FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
        #         FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE SET NULL,
        #         FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE RESTRICT,
        #         FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE SET NULL
        #     )
        # """)

        # Indexes for invoicing tables now created by InvoicingEngine
        # conn.execute("CREATE INDEX IF NOT EXISTS idx_customers_org ON customers(organization_id)")
        # conn.execute("CREATE INDEX IF NOT EXISTS idx_customers_entity ON customers(entity_id)")
        # conn.execute("CREATE INDEX IF NOT EXISTS idx_invoices_org ON invoices(organization_id)")
        # conn.execute("CREATE INDEX IF NOT EXISTS idx_invoices_customer ON invoices(customer_id)")
        # conn.execute("CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status)")
        # conn.execute("CREATE INDEX IF NOT EXISTS idx_invoices_due_date ON invoices(due_date)")
        # conn.execute("CREATE INDEX IF NOT EXISTS idx_invoice_items_invoice ON invoice_items(invoice_id)")
        # conn.execute("CREATE INDEX IF NOT EXISTS idx_payments_org ON payments(organization_id)")
        # conn.execute("CREATE INDEX IF NOT EXISTS idx_payments_customer ON payments(customer_id)")
        # conn.execute("CREATE INDEX IF NOT EXISTS idx_payments_invoice ON payments(invoice_id)")

        # =================================================================
        # VENDORS & BILLS (ACCOUNTS PAYABLE)
        # =================================================================

        # Vendors table is now created by BillsEngine (app/bills/engine.py)
        # Commented out to avoid conflict with the new AP system
        # conn.execute("""
        #     CREATE TABLE IF NOT EXISTS vendors (
        #         id TEXT PRIMARY KEY,
        #         organization_id TEXT NOT NULL,
        #         entity_id TEXT,
        #         name TEXT NOT NULL,
        #         email TEXT,
        #         phone TEXT,
        #         address TEXT,
        #         city TEXT,
        #         state TEXT,
        #         zip TEXT,
        #         payment_terms INTEGER DEFAULT 30,
        #         ein TEXT,
        #         notes TEXT,
        #         total_billed REAL DEFAULT 0.0,
        #         total_paid REAL DEFAULT 0.0,
        #         amount_owed REAL DEFAULT 0.0,
        #         active_bills INTEGER DEFAULT 0,
        #         is_active INTEGER DEFAULT 1,
        #         created_at TEXT DEFAULT (datetime('now')),
        #         updated_at TEXT DEFAULT (datetime('now')),
        #         FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
        #         FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE SET NULL
        #     )
        # """)

        # Bills and Bill_payments tables now created by BillsEngine (app/bills/engine.py)
        # Commented out to avoid conflict with the new AP system
        # conn.execute("""
        #     CREATE TABLE IF NOT EXISTS bills (
        #         id TEXT PRIMARY KEY,
        #         organization_id TEXT NOT NULL,
        #         entity_id TEXT,
        #         vendor_id TEXT NOT NULL,
        #         bill_number TEXT,
        #         bill_date TEXT NOT NULL,
        #         due_date TEXT NOT NULL,
        #         amount TEXT NOT NULL,
        #         amount_paid TEXT DEFAULT '0.00',
        #         amount_due TEXT NOT NULL,
        #         status TEXT DEFAULT 'pending',
        #         description TEXT,
        #         category TEXT,
        #         notes TEXT,
        #         created_at TEXT DEFAULT (datetime('now')),
        #         updated_at TEXT DEFAULT (datetime('now')),
        #         FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
        #         FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE SET NULL,
        #         FOREIGN KEY (vendor_id) REFERENCES vendors(id) ON DELETE RESTRICT
        #     )
        # """)

        # conn.execute("""
        #     CREATE TABLE IF NOT EXISTS bill_payments (
        #         id TEXT PRIMARY KEY,
        #         organization_id TEXT NOT NULL,
        #         entity_id TEXT,
        #         vendor_id TEXT,
        #         bill_id TEXT NOT NULL,
        #         payment_date TEXT NOT NULL,
        #         amount REAL NOT NULL,
        #         payment_method TEXT,
        #         reference_number TEXT,
        #         notes TEXT,
        #         created_at TEXT DEFAULT (datetime('now')),
        #         FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
        #         FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE SET NULL,
        #         FOREIGN KEY (vendor_id) REFERENCES vendors(id) ON DELETE RESTRICT,
        #         FOREIGN KEY (bill_id) REFERENCES bills(id) ON DELETE CASCADE
        #     )
        # """)

        # Indexes for vendors/bills now created by BillsEngine
        # conn.execute("CREATE INDEX IF NOT EXISTS idx_vendors_org ON vendors(organization_id)")
        # conn.execute("CREATE INDEX IF NOT EXISTS idx_vendors_entity ON vendors(entity_id)")
        # conn.execute("CREATE INDEX IF NOT EXISTS idx_bills_org ON bills(organization_id)")
        # conn.execute("CREATE INDEX IF NOT EXISTS idx_bills_vendor ON bills(vendor_id)")
        # conn.execute("CREATE INDEX IF NOT EXISTS idx_bills_status ON bills(status)")
        # conn.execute("CREATE INDEX IF NOT EXISTS idx_bills_due_date ON bills(due_date)")
        # conn.execute("CREATE INDEX IF NOT EXISTS idx_bill_payments_bill ON bill_payments(bill_id)")
        # conn.execute("CREATE INDEX IF NOT EXISTS idx_bill_payments_vendor ON bill_payments(vendor_id)")

        # =================================================================
        # STEPS 15-19: GOVERNANCE & DEPLOYMENT CONTROL
        # =================================================================

        # Step 15: Deploy Runs
        conn.execute("""
            CREATE TABLE IF NOT EXISTS deploy_runs (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'draft',
                commit_sha TEXT,
                preview_url TEXT,
                initiated_by TEXT,
                approved_by TEXT,
                approval_signature TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)

        # Step 16: System State
        conn.execute("""
            CREATE TABLE IF NOT EXISTS system_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                incident_mode INTEGER NOT NULL DEFAULT 0,
                last_rollback_at TEXT,
                rolled_back_to_run_id TEXT,
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("INSERT OR IGNORE INTO system_state (id) VALUES (1)")

        # Step 17: Deploy Run Approvals
        conn.execute("""
            CREATE TABLE IF NOT EXISTS deploy_run_approvals (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                approved_by TEXT NOT NULL,
                approved_at TEXT DEFAULT (datetime('now'))
            )
        """)

        # Step 18: Audit Log
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id TEXT PRIMARY KEY,
                action TEXT NOT NULL,
                actor TEXT NOT NULL,
                run_id TEXT,
                metadata TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)

        # Step 19: Feature Flags
        conn.execute("""
            CREATE TABLE IF NOT EXISTS feature_flags (
                id TEXT PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 0,
                run_id TEXT,
                description TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)

        # =================================================================
        # GOVCON: APPEND-ONLY AUDIT EVENTS (DCAA Compliance)
        # =================================================================
        # This table is APPEND-ONLY. No UPDATE/DELETE operations are permitted.
        # Hash chaining ensures tamper-evidence (each event references prior hash).
        # Retention: 6 years per FAR requirements.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_events (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                actor_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT,
                payload TEXT NOT NULL,
                prev_hash TEXT,
                event_hash TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_events_created_at ON audit_events(created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_events_entity ON audit_events(entity_type, entity_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_events_actor ON audit_events(actor_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_events_type ON audit_events(event_type)")

        # =================================================================
        # PLAID INTEGRATION TABLES
        # =================================================================

        # Plaid Items (connected bank accounts)
        # Access tokens are encrypted at rest using AES-256-GCM
        # lifecycle: created|pending|processing|ready|login_required|error
        conn.execute("""
            CREATE TABLE IF NOT EXISTS plaid_items (
                id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                entity_id TEXT,
                item_id TEXT NOT NULL UNIQUE,
                access_token_encrypted TEXT NOT NULL,
                institution_id TEXT,
                institution_name TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                lifecycle TEXT DEFAULT 'created',
                sync_cursor TEXT,
                last_synced_at TEXT,
                error_code TEXT,
                error_message TEXT,
                webhook_url TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                created_by TEXT NOT NULL,
                FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
                FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE SET NULL,
                FOREIGN KEY (created_by) REFERENCES users(id)
            )
        """)
        
        # Migration: Add lifecycle column if missing (for existing databases)
        try:
            conn.execute("ALTER TABLE plaid_items ADD COLUMN lifecycle TEXT DEFAULT 'created'")
        except sqlite3.OperationalError:
            pass  # Column already exists
        
        conn.execute("CREATE INDEX IF NOT EXISTS idx_plaid_items_org ON plaid_items(organization_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_plaid_items_item_id ON plaid_items(item_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_plaid_items_status ON plaid_items(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_plaid_items_lifecycle ON plaid_items(lifecycle)")

        # Plaid Audit Log (immutable - append only)
        # Records all sensitive Plaid operations for compliance
        conn.execute("""
            CREATE TABLE IF NOT EXISTS plaid_audit_log (
                id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                item_id TEXT,
                action TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                request_id TEXT NOT NULL,
                details TEXT NOT NULL DEFAULT '{}',
                ip_address TEXT,
                user_agent TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_plaid_audit_org ON plaid_audit_log(organization_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_plaid_audit_item ON plaid_audit_log(item_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_plaid_audit_action ON plaid_audit_log(action)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_plaid_audit_created ON plaid_audit_log(created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_plaid_audit_request ON plaid_audit_log(request_id)")

        # Plaid Webhook Events (for idempotency and debugging)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS plaid_webhook_events (
                id TEXT PRIMARY KEY,
                item_id TEXT NOT NULL,
                webhook_type TEXT NOT NULL,
                webhook_code TEXT NOT NULL,
                payload TEXT NOT NULL,
                processed INTEGER DEFAULT 0,
                processed_at TEXT,
                error_message TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_plaid_webhook_item ON plaid_webhook_events(item_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_plaid_webhook_processed ON plaid_webhook_events(processed)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_plaid_webhook_created ON plaid_webhook_events(created_at)")

        # =================================================================
        # CORE SYNC TABLES (Single source of truth for org state)
        # =================================================================

        # CORE sync metadata - tracks sync state per organization
        # sync_status: 'never' | 'running' | 'success' | 'failed'
        # sync_started_at: Set immediately when sync begins
        # last_successful_sync_at: ONLY set on FULL successful sync (never partial)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS core_sync_metadata (
                id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL UNIQUE,
                sync_status TEXT DEFAULT 'never',
                sync_started_at TEXT,
                last_synced_at TEXT,
                last_successful_sync_at TEXT,
                last_sync_request_id TEXT,
                transactions_synced INTEGER,
                entities_derived INTEGER,
                error_message TEXT,
                last_retry_at TEXT,
                retry_count INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_core_sync_org ON core_sync_metadata(organization_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_core_sync_status ON core_sync_metadata(sync_status)")

        # CORE transactions - persisted from Plaid, normalized
        conn.execute("""
            CREATE TABLE IF NOT EXISTS core_transactions (
                id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                plaid_transaction_id TEXT UNIQUE,
                plaid_item_id TEXT,
                account_id TEXT,
                amount REAL NOT NULL,
                date TEXT NOT NULL,
                name TEXT NOT NULL,
                merchant_name TEXT,
                merchant_normalized TEXT,
                category TEXT,
                category_id TEXT,
                pending INTEGER DEFAULT 0,
                payment_channel TEXT,
                iso_currency_code TEXT DEFAULT 'USD',
                transaction_type TEXT,
                is_income INTEGER DEFAULT 0,
                is_expense INTEGER DEFAULT 0,
                linked_vendor_id TEXT,
                linked_customer_id TEXT,
                linked_invoice_id TEXT,
                linked_bill_id TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_core_tx_org ON core_transactions(organization_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_core_tx_plaid_id ON core_transactions(plaid_transaction_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_core_tx_date ON core_transactions(date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_core_tx_merchant ON core_transactions(merchant_normalized)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_core_tx_item ON core_transactions(plaid_item_id)")

        # PERFORMANCE: Composite index for org + date queries (CFO reports, balance history, etc.)
        # This index optimizes queries that filter by organization_id AND order by date
        # Required per Performance Agent finding - Phase 1 Backend Delta
        conn.execute("CREATE INDEX IF NOT EXISTS idx_core_tx_org_date ON core_transactions(organization_id, date)")

        # =================================================================
        # S3 EXPORTS (Secure Export Downloads)
        # =================================================================
        # Tracks S3-based exports with signed URL access
        # S3 objects remain private; access is brokered via backend
        conn.execute("""
            CREATE TABLE IF NOT EXISTS s3_exports (
                id TEXT PRIMARY KEY,
                org_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                s3_key TEXT NOT NULL,
                filename TEXT NOT NULL,
                file_type TEXT NOT NULL,
                size_bytes INTEGER,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT DEFAULT (datetime('now')),
                completed_at TEXT,
                expires_at TEXT,
                FOREIGN KEY (org_id) REFERENCES organizations(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_s3_exports_org ON s3_exports(org_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_s3_exports_user ON s3_exports(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_s3_exports_status ON s3_exports(status)")

        # =================================================================
        # EXPORT EVIDENCE LINKS (Provenance Chain)
        # =================================================================
        # Links exports to their source evidence records
        # INSERT-ONLY: No updates or deletes permitted
        # Enables traceability: export -> evidence -> source data
        #
        # IMMUTABILITY GUARANTEE:
        # - ON DELETE NO ACTION: Provenance records MUST outlive exports
        # - Even if artifact is deleted/expired, the chain remains
        # - Fields (evidence_type, linked_by) are informational only
        # - Linkage is immutable and authoritative
        conn.execute("""
            CREATE TABLE IF NOT EXISTS export_evidence_links (
                id TEXT PRIMARY KEY,
                export_id TEXT NOT NULL,
                evidence_id TEXT NOT NULL,
                evidence_type TEXT NOT NULL,
                linked_at TEXT NOT NULL DEFAULT (datetime('now')),
                linked_by TEXT NOT NULL,
                FOREIGN KEY (export_id) REFERENCES s3_exports(id) ON DELETE NO ACTION
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_exp_ev_links_export ON export_evidence_links(export_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_exp_ev_links_evidence ON export_evidence_links(evidence_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_exp_ev_links_type ON export_evidence_links(evidence_type)")

        # =================================================================
        # PHASE 4: CONTROL-PLANE SCHEMA (P1 Endpoints Support)
        # =================================================================
        # These tables support the P1 manual-first endpoints:
        # - /api/signals (advisory intelligence)
        # - /api/receipts (receipt/statement fallback)
        # - /api/export-pack (manual export requests)
        # - /api/retention (evidence retention policies)
        # - /api/rbac (effective permissions snapshot)

        # 001: Intelligence Signals (advisory-only, confidence-gated)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS intelligence_signals (
                signal_id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                confidence REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
                evidence_ref TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (organization_id) REFERENCES organizations(id)
            )
        """)

        # 001b: Exception Resolutions (Phase 6.4 — append-only resolution tracking)
        # Links to intelligence_signals, does NOT modify signals table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS exception_resolutions (
                resolution_id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id INTEGER NOT NULL,
                organization_id INTEGER NOT NULL,
                resolution_type TEXT NOT NULL CHECK (resolution_type IN ('acknowledged', 'dismissed', 'resolved', 'deferred')),
                resolution_note TEXT,
                resolved_by TEXT NOT NULL,
                resolved_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (signal_id) REFERENCES intelligence_signals(signal_id),
                FOREIGN KEY (organization_id) REFERENCES organizations(id)
            )
        """)

        # Index for efficient resolution lookups
        conn.execute("CREATE INDEX IF NOT EXISTS idx_resolutions_signal ON exception_resolutions(signal_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_resolutions_org ON exception_resolutions(organization_id)")

        # 002: Receipts
        conn.execute("""
            CREATE TABLE IF NOT EXISTS receipts (
                receipt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id INTEGER NOT NULL,
                source TEXT NOT NULL,
                total REAL NOT NULL,
                currency TEXT NOT NULL DEFAULT 'USD',
                received_date TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (organization_id) REFERENCES organizations(id)
            )
        """)

        # 003: Statements (fallback for receipts endpoint)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS statements (
                statement_id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id INTEGER NOT NULL,
                source TEXT NOT NULL,
                total REAL NOT NULL,
                currency TEXT NOT NULL DEFAULT 'USD',
                posted_date TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (organization_id) REFERENCES organizations(id)
            )
        """)

        # 004: Export Packs (manual request, no auto-execute)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS export_packs (
                export_pack_id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id INTEGER NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('requested', 'running', 'completed', 'failed')),
                requested_at TEXT NOT NULL,
                FOREIGN KEY (organization_id) REFERENCES organizations(id)
            )
        """)

        # 005: Retention Policies (evidence scope)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS retention_policies (
                policy_id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id INTEGER NOT NULL,
                scope TEXT NOT NULL,
                policy_name TEXT NOT NULL,
                retention_days INTEGER NOT NULL CHECK (retention_days >= 0),
                enforced_from TEXT NOT NULL,
                FOREIGN KEY (organization_id) REFERENCES organizations(id)
            )
        """)

        # 006: RBAC Effective Permissions (snapshot view)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rbac_effective_permissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                permission TEXT NOT NULL,
                FOREIGN KEY (organization_id) REFERENCES organizations(id)
            )
        """)

        conn.commit()
        print("Multi-tenancy database tables created")

    # Initialize document pipeline tables
    from app.services.document_service import init_document_tables
    init_document_tables()
