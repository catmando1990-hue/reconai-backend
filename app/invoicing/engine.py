# app/invoicing/engine.py

from __future__ import annotations
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional, Dict
import sqlite3
from pathlib import Path
import uuid

from .models import (
    Customer,
    CustomerCreate,
    CustomerUpdate,
    Invoice,
    InvoiceCreate,
    InvoiceUpdate,
    InvoiceStatus,
    InvoiceItem,
    InvoiceItemCreate,
    Payment,
    PaymentCreate,
    PaymentMethod,
    ARAgingReport,
    ARAgingBucket
)


class InvoicingEngine:
    """
    Invoicing and Accounts Receivable Engine.

    Implements:
    - Customer management
    - Invoice generation and tracking
    - Payment recording
    - AR aging reports
    - Auto journal entry creation
    """

    def __init__(self, db_path: str | Path, bookkeeper_engine=None):
        """
        Initialize invoicing engine.

        Args:
            db_path: Path to SQLite database
            bookkeeper_engine: Optional BookkeeperEngine for automatic journal entries
        """
        self.db_path = Path(db_path)
        self.bookkeeper = bookkeeper_engine
        self._init_database()

    def _init_database(self):
        """Create database tables if they don't exist"""
        with sqlite3.connect(self.db_path) as conn:
            # Customers table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS customers (
                    customer_id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    email TEXT,
                    phone TEXT,
                    billing_address TEXT,
                    shipping_address TEXT,
                    payment_terms INTEGER DEFAULT 30,
                    tax_rate TEXT DEFAULT '0.00',
                    notes TEXT,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE
                )
            """)

            # Invoices table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS invoices (
                    invoice_id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    customer_id TEXT NOT NULL,
                    invoice_number TEXT NOT NULL UNIQUE,
                    invoice_date TEXT NOT NULL,
                    due_date TEXT NOT NULL,
                    status TEXT DEFAULT 'draft',
                    subtotal TEXT DEFAULT '0.00',
                    tax_rate TEXT DEFAULT '0.00',
                    tax_amount TEXT DEFAULT '0.00',
                    discount_amount TEXT DEFAULT '0.00',
                    total TEXT DEFAULT '0.00',
                    amount_paid TEXT DEFAULT '0.00',
                    balance_due TEXT DEFAULT '0.00',
                    notes TEXT,
                    terms TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now')),
                    sent_at TEXT,
                    paid_at TEXT,
                    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
                    FOREIGN KEY (customer_id) REFERENCES customers(customer_id) ON DELETE CASCADE
                )
            """)

            # Invoice Items table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS invoice_items (
                    item_id TEXT PRIMARY KEY,
                    invoice_id TEXT NOT NULL,
                    description TEXT NOT NULL,
                    quantity TEXT DEFAULT '1.00',
                    rate TEXT NOT NULL,
                    amount TEXT NOT NULL,
                    line_order INTEGER DEFAULT 0,
                    FOREIGN KEY (invoice_id) REFERENCES invoices(invoice_id) ON DELETE CASCADE
                )
            """)

            # Payments table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS payments (
                    payment_id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    customer_id TEXT NOT NULL,
                    invoice_id TEXT NOT NULL,
                    payment_date TEXT NOT NULL,
                    amount TEXT NOT NULL,
                    payment_method TEXT,
                    reference TEXT,
                    notes TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
                    FOREIGN KEY (customer_id) REFERENCES customers(customer_id) ON DELETE CASCADE,
                    FOREIGN KEY (invoice_id) REFERENCES invoices(invoice_id) ON DELETE CASCADE
                )
            """)

            # Create indexes for performance
            conn.execute("CREATE INDEX IF NOT EXISTS idx_customers_org ON customers(organization_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_customers_active ON customers(is_active)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_invoices_org ON invoices(organization_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_invoices_customer ON invoices(customer_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_invoices_due_date ON invoices(due_date)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_payments_invoice ON payments(invoice_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_payments_customer ON payments(customer_id)")

            conn.commit()

    # ========================================================================
    # CUSTOMER MANAGEMENT
    # ========================================================================

    def create_customer(self, customer_data: CustomerCreate, organization_id: str) -> Customer:
        """Create a new customer"""
        customer_id = str(uuid.uuid4())

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO customers (
                    customer_id, organization_id, name, email, phone,
                    billing_address, shipping_address, payment_terms, tax_rate, notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                customer_id,
                organization_id,
                customer_data.name,
                customer_data.email,
                customer_data.phone,
                customer_data.billing_address,
                customer_data.shipping_address,
                customer_data.payment_terms,
                str(customer_data.tax_rate),
                customer_data.notes
            ))
            conn.commit()

        return self.get_customer(customer_id)

    def get_customer(self, customer_id: str) -> Optional[Customer]:
        """Get customer by ID"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT
                    c.*,
                    COALESCE(SUM(i.total), 0) as total_billed,
                    COALESCE(SUM(i.amount_paid), 0) as total_paid,
                    COALESCE(SUM(i.balance_due), 0) as balance_due
                FROM customers c
                LEFT JOIN invoices i ON c.customer_id = i.customer_id
                WHERE c.customer_id = ?
                GROUP BY c.customer_id
            """, (customer_id,))

            row = cursor.fetchone()
            if not row:
                return None

            return Customer(
                customer_id=row['customer_id'],
                organization_id=row['organization_id'],
                name=row['name'],
                email=row['email'],
                phone=row['phone'],
                billing_address=row['billing_address'],
                shipping_address=row['shipping_address'],
                payment_terms=row['payment_terms'],
                tax_rate=Decimal(row['tax_rate']),
                notes=row['notes'],
                is_active=bool(row['is_active']),
                created_at=datetime.fromisoformat(row['created_at']),
                updated_at=datetime.fromisoformat(row['updated_at']),
                total_billed=Decimal(str(row['total_billed'])),
                total_paid=Decimal(str(row['total_paid'])),
                balance_due=Decimal(str(row['balance_due']))
            )

    def list_customers(self, organization_id: str, active_only: bool = True) -> List[Customer]:
        """List all customers for an organization"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            query = """
                SELECT
                    c.*,
                    COALESCE(SUM(i.total), 0) as total_billed,
                    COALESCE(SUM(i.amount_paid), 0) as total_paid,
                    COALESCE(SUM(i.balance_due), 0) as balance_due
                FROM customers c
                LEFT JOIN invoices i ON c.customer_id = i.customer_id
                WHERE c.organization_id = ?
            """
            if active_only:
                query += " AND c.is_active = 1"
            query += " GROUP BY c.customer_id ORDER BY c.name"

            cursor = conn.execute(query, (organization_id,))
            rows = cursor.fetchall()

            customers = []
            for row in rows:
                customers.append(Customer(
                    customer_id=row['customer_id'],
                    organization_id=row['organization_id'],
                    name=row['name'],
                    email=row['email'],
                    phone=row['phone'],
                    billing_address=row['billing_address'],
                    shipping_address=row['shipping_address'],
                    payment_terms=row['payment_terms'],
                    tax_rate=Decimal(row['tax_rate']),
                    notes=row['notes'],
                    is_active=bool(row['is_active']),
                    created_at=datetime.fromisoformat(row['created_at']),
                    updated_at=datetime.fromisoformat(row['updated_at']),
                    total_billed=Decimal(str(row['total_billed'])),
                    total_paid=Decimal(str(row['total_paid'])),
                    balance_due=Decimal(str(row['balance_due']))
                ))

            return customers

    def update_customer(self, customer_id: str, updates: CustomerUpdate) -> Customer:
        """Update customer"""
        # P0 Security: Column allowlist to prevent SQL injection
        allowed_fields = {
            'name', 'email', 'phone', 'billing_address', 'shipping_address',
            'payment_terms', 'tax_rate', 'notes', 'is_active'
        }

        update_fields = []
        params = []

        for field, value in updates.model_dump(exclude_unset=True).items():
            # Only allow whitelisted fields
            if field not in allowed_fields:
                continue
            if value is not None:
                update_fields.append(f"{field} = ?")
                params.append(str(value) if isinstance(value, Decimal) else value)

        if not update_fields:
            return self.get_customer(customer_id)

        update_fields.append("updated_at = datetime('now')")
        params.append(customer_id)

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(f"""
                UPDATE customers
                SET {', '.join(update_fields)}
                WHERE customer_id = ?
            """, params)
            conn.commit()

        return self.get_customer(customer_id)

    def delete_customer(self, customer_id: str) -> bool:
        """Soft delete customer (set is_active = 0)"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE customers
                SET is_active = 0, updated_at = datetime('now')
                WHERE customer_id = ?
            """, (customer_id,))
            conn.commit()
            return conn.total_changes > 0

    # ========================================================================
    # INVOICE MANAGEMENT
    # ========================================================================

    def _generate_invoice_number(self, organization_id: str) -> str:
        """Generate next invoice number (INV-0001, INV-0002, etc.)"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT invoice_number FROM invoices
                WHERE organization_id = ?
                ORDER BY created_at DESC
                LIMIT 1
            """, (organization_id,))

            row = cursor.fetchone()
            if not row:
                return "INV-0001"

            last_number = row[0]
            # Extract number from "INV-0001"
            try:
                num_part = int(last_number.split('-')[1])
                return f"INV-{num_part + 1:04d}"
            except (ValueError, IndexError):
                return "INV-0001"

    def create_invoice(self, invoice_data: InvoiceCreate, organization_id: str) -> Invoice:
        """Create a new invoice"""
        invoice_id = str(uuid.uuid4())
        invoice_number = self._generate_invoice_number(organization_id)

        # Calculate totals
        subtotal = sum(item.quantity * item.rate for item in invoice_data.items)
        subtotal_after_discount = subtotal - invoice_data.discount_amount
        tax_amount = subtotal_after_discount * invoice_data.tax_rate
        total = subtotal_after_discount + tax_amount

        with sqlite3.connect(self.db_path) as conn:
            # Create invoice
            conn.execute("""
                INSERT INTO invoices (
                    invoice_id, organization_id, customer_id, invoice_number,
                    invoice_date, due_date, status,
                    subtotal, tax_rate, tax_amount, discount_amount, total,
                    amount_paid, balance_due, notes, terms
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                invoice_id, organization_id, invoice_data.customer_id, invoice_number,
                invoice_data.invoice_date.isoformat(), invoice_data.due_date.isoformat(),
                InvoiceStatus.DRAFT.value,
                str(subtotal), str(invoice_data.tax_rate), str(tax_amount),
                str(invoice_data.discount_amount), str(total),
                "0.00", str(total),  # amount_paid=0, balance_due=total
                invoice_data.notes, invoice_data.terms
            ))

            # Create invoice items
            for idx, item in enumerate(invoice_data.items):
                item_id = str(uuid.uuid4())
                amount = item.quantity * item.rate
                conn.execute("""
                    INSERT INTO invoice_items (
                        item_id, invoice_id, description, quantity, rate, amount, line_order
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    item_id, invoice_id, item.description,
                    str(item.quantity), str(item.rate), str(amount), idx
                ))

            conn.commit()

        return self.get_invoice(invoice_id)

    def get_invoice(self, invoice_id: str) -> Optional[Invoice]:
        """Get invoice by ID with items"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Get invoice
            cursor = conn.execute("""
                SELECT * FROM invoices WHERE invoice_id = ?
            """, (invoice_id,))
            invoice_row = cursor.fetchone()

            if not invoice_row:
                return None

            # Get items
            cursor = conn.execute("""
                SELECT * FROM invoice_items
                WHERE invoice_id = ?
                ORDER BY line_order
            """, (invoice_id,))
            item_rows = cursor.fetchall()

            items = [
                InvoiceItem(
                    item_id=row['item_id'],
                    invoice_id=row['invoice_id'],
                    description=row['description'],
                    quantity=Decimal(row['quantity']),
                    rate=Decimal(row['rate']),
                    amount=Decimal(row['amount']),
                    line_order=row['line_order']
                )
                for row in item_rows
            ]

            invoice = Invoice(
                invoice_id=invoice_row['invoice_id'],
                organization_id=invoice_row['organization_id'],
                customer_id=invoice_row['customer_id'],
                invoice_number=invoice_row['invoice_number'],
                invoice_date=date.fromisoformat(invoice_row['invoice_date']),
                due_date=date.fromisoformat(invoice_row['due_date']),
                status=InvoiceStatus(invoice_row['status']),
                subtotal=Decimal(invoice_row['subtotal']),
                tax_rate=Decimal(invoice_row['tax_rate']),
                tax_amount=Decimal(invoice_row['tax_amount']),
                discount_amount=Decimal(invoice_row['discount_amount']),
                total=Decimal(invoice_row['total']),
                amount_paid=Decimal(invoice_row['amount_paid']),
                balance_due=Decimal(invoice_row['balance_due']),
                notes=invoice_row['notes'],
                terms=invoice_row['terms'],
                created_at=datetime.fromisoformat(invoice_row['created_at']),
                updated_at=datetime.fromisoformat(invoice_row['updated_at']),
                sent_at=datetime.fromisoformat(invoice_row['sent_at']) if invoice_row['sent_at'] else None,
                paid_at=datetime.fromisoformat(invoice_row['paid_at']) if invoice_row['paid_at'] else None,
                items=items
            )

            return invoice

    def list_invoices(
        self,
        organization_id: str,
        customer_id: Optional[str] = None,
        status: Optional[InvoiceStatus] = None,
        overdue_only: bool = False
    ) -> List[Invoice]:
        """List invoices with optional filters"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            query = "SELECT * FROM invoices WHERE organization_id = ?"
            params = [organization_id]

            if customer_id:
                query += " AND customer_id = ?"
                params.append(customer_id)

            if status:
                query += " AND status = ?"
                params.append(status.value)

            if overdue_only:
                query += " AND status = ? AND due_date < ?"
                params.append(InvoiceStatus.OVERDUE.value)
                params.append(date.today().isoformat())

            query += " ORDER BY invoice_date DESC, invoice_number DESC"

            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

            invoices = []
            for row in rows:
                invoice = self.get_invoice(row['invoice_id'])
                if invoice:
                    invoices.append(invoice)

            return invoices

    def send_invoice(self, invoice_id: str) -> Invoice:
        """Mark invoice as sent"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE invoices
                SET status = ?, sent_at = datetime('now'), updated_at = datetime('now')
                WHERE invoice_id = ? AND status = ?
            """, (InvoiceStatus.SENT.value, invoice_id, InvoiceStatus.DRAFT.value))
            conn.commit()

            # Create journal entry if bookkeeper is available
            if self.bookkeeper and conn.total_changes > 0:
                invoice = self.get_invoice(invoice_id)
                if invoice:
                    self._create_invoice_journal_entry(invoice)

        return self.get_invoice(invoice_id)

    def cancel_invoice(self, invoice_id: str) -> Invoice:
        """Cancel an invoice"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE invoices
                SET status = ?, updated_at = datetime('now')
                WHERE invoice_id = ?
            """, (InvoiceStatus.CANCELLED.value, invoice_id))
            conn.commit()

        return self.get_invoice(invoice_id)

    # ========================================================================
    # PAYMENT MANAGEMENT
    # ========================================================================

    def record_payment(self, payment_data: PaymentCreate, organization_id: str) -> Payment:
        """Record a payment against an invoice"""
        payment_id = str(uuid.uuid4())

        # Get invoice to validate payment amount and get customer_id
        invoice = self.get_invoice(payment_data.invoice_id)
        if not invoice:
            raise ValueError(f"Invoice {payment_data.invoice_id} not found")

        if payment_data.amount > invoice.balance_due:
            raise ValueError(f"Payment amount ${payment_data.amount} exceeds balance due ${invoice.balance_due}")

        with sqlite3.connect(self.db_path) as conn:
            # Create payment record
            conn.execute("""
                INSERT INTO payments (
                    payment_id, organization_id, customer_id, invoice_id,
                    payment_date, amount, payment_method, reference, notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                payment_id, organization_id, invoice.customer_id, payment_data.invoice_id,
                payment_data.payment_date.isoformat(), str(payment_data.amount),
                payment_data.payment_method.value, payment_data.reference, payment_data.notes
            ))

            # Update invoice amounts
            new_amount_paid = invoice.amount_paid + payment_data.amount
            new_balance_due = invoice.total - new_amount_paid

            # Determine new status
            if new_balance_due <= Decimal("0.01"):  # Allow for rounding
                new_status = InvoiceStatus.PAID
                paid_at = datetime.now().isoformat()
            elif new_amount_paid > 0:
                new_status = InvoiceStatus.PARTIAL
                paid_at = None
            else:
                new_status = invoice.status
                paid_at = None

            conn.execute("""
                UPDATE invoices
                SET amount_paid = ?, balance_due = ?, status = ?, paid_at = ?, updated_at = datetime('now')
                WHERE invoice_id = ?
            """, (str(new_amount_paid), str(new_balance_due), new_status.value, paid_at, payment_data.invoice_id))

            conn.commit()

            # Create journal entry if bookkeeper is available
            if self.bookkeeper:
                updated_invoice = self.get_invoice(payment_data.invoice_id)
                payment = Payment(
                    payment_id=payment_id,
                    organization_id=organization_id,
                    customer_id=invoice.customer_id,
                    invoice_id=payment_data.invoice_id,
                    payment_date=payment_data.payment_date,
                    amount=payment_data.amount,
                    payment_method=payment_data.payment_method,
                    reference=payment_data.reference,
                    notes=payment_data.notes
                )
                self._create_payment_journal_entry(payment, updated_invoice)

        return self.get_payment(payment_id)

    def get_payment(self, payment_id: str) -> Optional[Payment]:
        """Get payment by ID"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM payments WHERE payment_id = ?
            """, (payment_id,))
            row = cursor.fetchone()

            if not row:
                return None

            return Payment(
                payment_id=row['payment_id'],
                organization_id=row['organization_id'],
                customer_id=row['customer_id'],
                invoice_id=row['invoice_id'],
                payment_date=date.fromisoformat(row['payment_date']),
                amount=Decimal(row['amount']),
                payment_method=PaymentMethod(row['payment_method']),
                reference=row['reference'],
                notes=row['notes'],
                created_at=datetime.fromisoformat(row['created_at'])
            )

    def list_payments(self, organization_id: str, invoice_id: Optional[str] = None) -> List[Payment]:
        """List payments"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            query = "SELECT * FROM payments WHERE organization_id = ?"
            params = [organization_id]

            if invoice_id:
                query += " AND invoice_id = ?"
                params.append(invoice_id)

            query += " ORDER BY payment_date DESC"

            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

            return [
                Payment(
                    payment_id=row['payment_id'],
                    organization_id=row['organization_id'],
                    customer_id=row['customer_id'],
                    invoice_id=row['invoice_id'],
                    payment_date=date.fromisoformat(row['payment_date']),
                    amount=Decimal(row['amount']),
                    payment_method=PaymentMethod(row['payment_method']),
                    reference=row['reference'],
                    notes=row['notes'],
                    created_at=datetime.fromisoformat(row['created_at'])
                )
                for row in rows
            ]

    # ========================================================================
    # REPORTS
    # ========================================================================

    def generate_ar_aging_report(self, organization_id: str, as_of_date: Optional[date] = None) -> ARAgingReport:
        """Generate Accounts Receivable Aging Report"""
        if not as_of_date:
            as_of_date = date.today()

        # Get all outstanding invoices
        invoices = self.list_invoices(organization_id)
        outstanding_invoices = [inv for inv in invoices if inv.balance_due > 0 and inv.status != InvoiceStatus.CANCELLED]

        # Initialize buckets
        buckets = {
            "current": ARAgingBucket(bucket_name="Current (0-30 days)"),
            "1_30": ARAgingBucket(bucket_name="1-30 days past due"),
            "31_60": ARAgingBucket(bucket_name="31-60 days past due"),
            "61_90": ARAgingBucket(bucket_name="61-90 days past due"),
            "90_plus": ARAgingBucket(bucket_name="90+ days past due")
        }

        # Categorize invoices
        for invoice in outstanding_invoices:
            days_past_due = (as_of_date - invoice.due_date).days

            if days_past_due < 0:
                bucket = buckets["current"]
            elif days_past_due <= 30:
                bucket = buckets["1_30"]
            elif days_past_due <= 60:
                bucket = buckets["31_60"]
            elif days_past_due <= 90:
                bucket = buckets["61_90"]
            else:
                bucket = buckets["90_plus"]

            bucket.invoice_count += 1
            bucket.total_amount += invoice.balance_due
            bucket.invoices.append(invoice)

        # Calculate totals
        report = ARAgingReport(
            report_date=as_of_date,
            organization_id=organization_id,
            total_current=buckets["current"].total_amount,
            total_1_30=buckets["1_30"].total_amount,
            total_31_60=buckets["31_60"].total_amount,
            total_61_90=buckets["61_90"].total_amount,
            total_90_plus=buckets["90_plus"].total_amount,
            buckets=list(buckets.values())
        )

        report.total_outstanding = (
            report.total_current +
            report.total_1_30 +
            report.total_31_60 +
            report.total_61_90 +
            report.total_90_plus
        )

        return report

    # ========================================================================
    # JOURNAL ENTRY INTEGRATION
    # ========================================================================

    def _create_invoice_journal_entry(self, invoice: Invoice):
        """Create journal entry when invoice is sent (A/R debit, Revenue credit)"""
        if not self.bookkeeper:
            return

        # When invoice is sent:
        # Debit: Accounts Receivable (1200)
        # Credit: Service Revenue (4000)

        from app.bookkeeping.models import JournalEntry, JournalEntryLine

        entry = JournalEntry(
            entry_date=invoice.invoice_date,
            description=f"Invoice {invoice.invoice_number} - Customer receivable",
            reference=invoice.invoice_number,
            lines=[
                JournalEntryLine(
                    account_id="1200",  # Accounts Receivable
                    debit=invoice.total,
                    credit=Decimal("0.00"),
                    memo=f"Invoice {invoice.invoice_number}"
                ),
                JournalEntryLine(
                    account_id="4000",  # Service Revenue
                    debit=Decimal("0.00"),
                    credit=invoice.total,
                    memo=f"Revenue from invoice {invoice.invoice_number}"
                )
            ]
        )

        try:
            self.bookkeeper.create_journal_entry(entry)
            self.bookkeeper.post_journal_entry(entry.entry_id)
        except Exception as e:
            print(f"Warning: Failed to create journal entry for invoice {invoice.invoice_number}: {e}")

    def _create_payment_journal_entry(self, payment: Payment, invoice: Invoice):
        """Create journal entry when payment is received (Cash debit, A/R credit)"""
        if not self.bookkeeper:
            return

        # When payment is received:
        # Debit: Cash/Bank Account (1000 or 1020)
        # Credit: Accounts Receivable (1200)

        from app.bookkeeping.models import JournalEntry, JournalEntryLine

        # Determine cash account based on payment method
        cash_account = "1020"  # Business Checking Account
        if payment.payment_method == PaymentMethod.CASH:
            cash_account = "1000"  # Cash - Operating

        entry = JournalEntry(
            entry_date=payment.payment_date,
            description=f"Payment received for invoice {invoice.invoice_number}",
            reference=payment.reference or invoice.invoice_number,
            lines=[
                JournalEntryLine(
                    account_id=cash_account,
                    debit=payment.amount,
                    credit=Decimal("0.00"),
                    memo=f"Payment received - {payment.payment_method.value}"
                ),
                JournalEntryLine(
                    account_id="1200",  # Accounts Receivable
                    debit=Decimal("0.00"),
                    credit=payment.amount,
                    memo=f"Payment for invoice {invoice.invoice_number}"
                )
            ]
        )

        try:
            self.bookkeeper.create_journal_entry(entry)
            self.bookkeeper.post_journal_entry(entry.entry_id)
        except Exception as e:
            print(f"Warning: Failed to create journal entry for payment {payment.payment_id}: {e}")
