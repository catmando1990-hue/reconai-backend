# app/db.py

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

# Portable data folder (Render persistent disk -> /var/data)
DATA_DIR = Path(os.getenv("DATA_DIR", "./data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

UPLOADS_DIR = Path(os.getenv("UPLOADS_DIR", str(DATA_DIR / "uploads")))
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = Path(os.getenv("DB_PATH", str(DATA_DIR / "reconai.db")))


def get_db_connection():
    """Get SQLite database connection"""
    return sqlite3.connect(DB_PATH)


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

        conn.commit()
        print("Multi-tenancy database tables created")
