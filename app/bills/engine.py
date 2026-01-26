# app/bills/engine.py

from __future__ import annotations
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional
import sqlite3
from pathlib import Path
import uuid

from .models import (
    Vendor,
    VendorCreate,
    VendorUpdate,
    Bill,
    BillCreate,
    BillUpdate,
    BillStatus,
    BillItem,
    BillItemCreate,
    BillPayment,
    BillPaymentCreate,
    PaymentMethod,
    APAgingReport,
    APAgingBucket,
    Vendor1099Report,
    Organization1099Summary
)


class BillsEngine:
    """
    Bills and Accounts Payable Engine.

    Implements:
    - Vendor management
    - Bill tracking and payment
    - AP aging reports
    - 1099 preparation
    - Auto journal entry creation
    """

    def __init__(self, db_path: str | Path, bookkeeper_engine=None):
        """
        Initialize bills engine.

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
            # Vendors table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS vendors (
                    vendor_id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    email TEXT,
                    phone TEXT,
                    address TEXT,
                    payment_terms INTEGER DEFAULT 30,
                    ein TEXT,
                    requires_1099 INTEGER DEFAULT 0,
                    notes TEXT,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE
                )
            """)

            # Bills table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS bills (
                    bill_id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    vendor_id TEXT NOT NULL,
                    bill_number TEXT,
                    bill_date TEXT NOT NULL,
                    due_date TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    total TEXT DEFAULT '0.00',
                    amount_paid TEXT DEFAULT '0.00',
                    balance_due TEXT DEFAULT '0.00',
                    notes TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now')),
                    paid_at TEXT,
                    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
                    FOREIGN KEY (vendor_id) REFERENCES vendors(vendor_id) ON DELETE CASCADE
                )
            """)

            # Bill Items table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS bill_items (
                    item_id TEXT PRIMARY KEY,
                    bill_id TEXT NOT NULL,
                    description TEXT NOT NULL,
                    category TEXT,
                    account_id TEXT,
                    amount TEXT NOT NULL,
                    line_order INTEGER DEFAULT 0,
                    FOREIGN KEY (bill_id) REFERENCES bills(bill_id) ON DELETE CASCADE
                )
            """)

            # Bill Payments table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS bill_payments (
                    payment_id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    vendor_id TEXT NOT NULL,
                    bill_id TEXT NOT NULL,
                    payment_date TEXT NOT NULL,
                    amount TEXT NOT NULL,
                    payment_method TEXT,
                    reference TEXT,
                    notes TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
                    FOREIGN KEY (vendor_id) REFERENCES vendors(vendor_id) ON DELETE CASCADE,
                    FOREIGN KEY (bill_id) REFERENCES bills(bill_id) ON DELETE CASCADE
                )
            """)

            # Migration: Add missing columns to existing tables
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(vendors)")
            vendor_columns = [col[1] for col in cursor.fetchall()]
            
            if "requires_1099" not in vendor_columns:
                conn.execute("ALTER TABLE vendors ADD COLUMN requires_1099 INTEGER DEFAULT 0")
            
            if "ein" not in vendor_columns:
                conn.execute("ALTER TABLE vendors ADD COLUMN ein TEXT")
            
            # Create indexes for performance
            conn.execute("CREATE INDEX IF NOT EXISTS idx_vendors_org ON vendors(organization_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_vendors_active ON vendors(is_active)")
            try:
                conn.execute("CREATE INDEX IF NOT EXISTS idx_vendors_1099 ON vendors(requires_1099)")
            except Exception:
                pass  # Column may not exist yet
            conn.execute("CREATE INDEX IF NOT EXISTS idx_bills_org ON bills(organization_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_bills_vendor ON bills(vendor_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_bills_status ON bills(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_bills_due_date ON bills(due_date)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_bill_payments_bill ON bill_payments(bill_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_bill_payments_vendor ON bill_payments(vendor_id)")

            conn.commit()

    # ========================================================================
    # VENDOR MANAGEMENT
    # ========================================================================

    def create_vendor(self, vendor_data: VendorCreate, organization_id: str) -> Vendor:
        """Create a new vendor"""
        vendor_id = str(uuid.uuid4())

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO vendors (
                    vendor_id, organization_id, name, email, phone,
                    address, payment_terms, ein, requires_1099, notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                vendor_id,
                organization_id,
                vendor_data.name,
                vendor_data.email,
                vendor_data.phone,
                vendor_data.address,
                vendor_data.payment_terms,
                vendor_data.ein,
                1 if vendor_data.requires_1099 else 0,
                vendor_data.notes
            ))
            conn.commit()

        return self.get_vendor(vendor_id)

    def get_vendor(self, vendor_id: str) -> Optional[Vendor]:
        """Get vendor by ID"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT
                    v.*,
                    COALESCE(SUM(b.total), 0) as total_billed,
                    COALESCE(SUM(b.amount_paid), 0) as total_paid,
                    COALESCE(SUM(b.balance_due), 0) as balance_due,
                    COALESCE(
                        (SELECT SUM(bp.amount) FROM bill_payments bp
                         WHERE bp.vendor_id = v.vendor_id
                         AND strftime('%Y', bp.payment_date) = strftime('%Y', 'now')),
                        0
                    ) as ytd_payments
                FROM vendors v
                LEFT JOIN bills b ON v.vendor_id = b.vendor_id
                WHERE v.vendor_id = ?
                GROUP BY v.vendor_id
            """, (vendor_id,))

            row = cursor.fetchone()
            if not row:
                return None

            return Vendor(
                vendor_id=row['vendor_id'],
                organization_id=row['organization_id'],
                name=row['name'],
                email=row['email'],
                phone=row['phone'],
                address=row['address'],
                payment_terms=row['payment_terms'],
                ein=row['ein'],
                requires_1099=bool(row['requires_1099']),
                notes=row['notes'],
                is_active=bool(row['is_active']),
                created_at=datetime.fromisoformat(row['created_at']),
                updated_at=datetime.fromisoformat(row['updated_at']),
                total_billed=Decimal(str(row['total_billed'])),
                total_paid=Decimal(str(row['total_paid'])),
                balance_due=Decimal(str(row['balance_due'])),
                ytd_payments=Decimal(str(row['ytd_payments']))
            )

    def list_vendors(self, organization_id: str, active_only: bool = True) -> List[Vendor]:
        """List all vendors for an organization"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            query = """
                SELECT
                    v.*,
                    COALESCE(SUM(b.total), 0) as total_billed,
                    COALESCE(SUM(b.amount_paid), 0) as total_paid,
                    COALESCE(SUM(b.balance_due), 0) as balance_due,
                    COALESCE(
                        (SELECT SUM(bp.amount) FROM bill_payments bp
                         WHERE bp.vendor_id = v.vendor_id
                         AND strftime('%Y', bp.payment_date) = strftime('%Y', 'now')),
                        0
                    ) as ytd_payments
                FROM vendors v
                LEFT JOIN bills b ON v.vendor_id = b.vendor_id
                WHERE v.organization_id = ?
            """
            if active_only:
                query += " AND v.is_active = 1"
            query += " GROUP BY v.vendor_id ORDER BY v.name"

            cursor = conn.execute(query, (organization_id,))
            rows = cursor.fetchall()

            vendors = []
            for row in rows:
                vendors.append(Vendor(
                    vendor_id=row['vendor_id'],
                    organization_id=row['organization_id'],
                    name=row['name'],
                    email=row['email'],
                    phone=row['phone'],
                    address=row['address'],
                    payment_terms=row['payment_terms'],
                    ein=row['ein'],
                    requires_1099=bool(row['requires_1099']),
                    notes=row['notes'],
                    is_active=bool(row['is_active']),
                    created_at=datetime.fromisoformat(row['created_at']),
                    updated_at=datetime.fromisoformat(row['updated_at']),
                    total_billed=Decimal(str(row['total_billed'])),
                    total_paid=Decimal(str(row['total_paid'])),
                    balance_due=Decimal(str(row['balance_due'])),
                    ytd_payments=Decimal(str(row['ytd_payments']))
                ))

            return vendors

    def update_vendor(self, vendor_id: str, updates: VendorUpdate) -> Vendor:
        """Update vendor"""
        # P0 Security: Column allowlist to prevent SQL injection
        allowed_fields = {
            'name', 'email', 'phone', 'address', 'payment_terms',
            'ein', 'requires_1099', 'notes', 'is_active'
        }

        update_fields = []
        params = []

        for field, value in updates.model_dump(exclude_unset=True).items():
            # Only allow whitelisted fields
            if field not in allowed_fields:
                continue
            if value is not None:
                if field == 'requires_1099':
                    update_fields.append(f"{field} = ?")
                    params.append(1 if value else 0)
                else:
                    update_fields.append(f"{field} = ?")
                    params.append(value)

        if not update_fields:
            return self.get_vendor(vendor_id)

        update_fields.append("updated_at = datetime('now')")
        params.append(vendor_id)

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(f"""
                UPDATE vendors
                SET {', '.join(update_fields)}
                WHERE vendor_id = ?
            """, params)
            conn.commit()

        return self.get_vendor(vendor_id)

    def delete_vendor(self, vendor_id: str) -> bool:
        """Soft delete vendor (set is_active = 0)"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE vendors
                SET is_active = 0, updated_at = datetime('now')
                WHERE vendor_id = ?
            """, (vendor_id,))
            conn.commit()
            return conn.total_changes > 0

    # ========================================================================
    # BILL MANAGEMENT
    # ========================================================================

    def create_bill(self, bill_data: BillCreate, organization_id: str) -> Bill:
        """Create a new bill"""
        bill_id = str(uuid.uuid4())

        # Calculate total
        total = sum(item.amount for item in bill_data.items)

        with sqlite3.connect(self.db_path) as conn:
            # Create bill
            conn.execute("""
                INSERT INTO bills (
                    bill_id, organization_id, vendor_id, bill_number,
                    bill_date, due_date, status,
                    total, amount_paid, balance_due, notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                bill_id, organization_id, bill_data.vendor_id, bill_data.bill_number,
                bill_data.bill_date.isoformat(), bill_data.due_date.isoformat(),
                BillStatus.PENDING.value,
                str(total), "0.00", str(total),
                bill_data.notes
            ))

            # Create bill items
            for idx, item in enumerate(bill_data.items):
                item_id = str(uuid.uuid4())
                conn.execute("""
                    INSERT INTO bill_items (
                        item_id, bill_id, description, category, account_id, amount, line_order
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    item_id, bill_id, item.description,
                    item.category, item.account_id, str(item.amount), idx
                ))

            conn.commit()

            # Create journal entry if bookkeeper is available
            if self.bookkeeper:
                bill = self.get_bill(bill_id)
                if bill:
                    self._create_bill_journal_entry(bill)

        return self.get_bill(bill_id)

    def get_bill(self, bill_id: str) -> Optional[Bill]:
        """Get bill by ID with items"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Get bill
            cursor = conn.execute("""
                SELECT * FROM bills WHERE bill_id = ?
            """, (bill_id,))
            bill_row = cursor.fetchone()

            if not bill_row:
                return None

            # Get items
            cursor = conn.execute("""
                SELECT * FROM bill_items
                WHERE bill_id = ?
                ORDER BY line_order
            """, (bill_id,))
            item_rows = cursor.fetchall()

            items = [
                BillItem(
                    item_id=row['item_id'],
                    bill_id=row['bill_id'],
                    description=row['description'],
                    category=row['category'],
                    account_id=row['account_id'],
                    amount=Decimal(row['amount']),
                    line_order=row['line_order']
                )
                for row in item_rows
            ]

            bill = Bill(
                bill_id=bill_row['bill_id'],
                organization_id=bill_row['organization_id'],
                vendor_id=bill_row['vendor_id'],
                bill_number=bill_row['bill_number'],
                bill_date=date.fromisoformat(bill_row['bill_date']),
                due_date=date.fromisoformat(bill_row['due_date']),
                status=BillStatus(bill_row['status']),
                total=Decimal(bill_row['total']),
                amount_paid=Decimal(bill_row['amount_paid']),
                balance_due=Decimal(bill_row['balance_due']),
                notes=bill_row['notes'],
                created_at=datetime.fromisoformat(bill_row['created_at']),
                updated_at=datetime.fromisoformat(bill_row['updated_at']),
                paid_at=datetime.fromisoformat(bill_row['paid_at']) if bill_row['paid_at'] else None,
                items=items
            )

            return bill

    def list_bills(
        self,
        organization_id: str,
        vendor_id: Optional[str] = None,
        status: Optional[BillStatus] = None,
        overdue_only: bool = False
    ) -> List[Bill]:
        """List bills with optional filters"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            query = "SELECT * FROM bills WHERE organization_id = ?"
            params = [organization_id]

            if vendor_id:
                query += " AND vendor_id = ?"
                params.append(vendor_id)

            if status:
                query += " AND status = ?"
                params.append(status.value)

            if overdue_only:
                query += " AND status = ? AND due_date < ?"
                params.append(BillStatus.OVERDUE.value)
                params.append(date.today().isoformat())

            query += " ORDER BY bill_date DESC"

            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

            bills = []
            for row in rows:
                bill = self.get_bill(row['bill_id'])
                if bill:
                    bills.append(bill)

            return bills

    # ========================================================================
    # BILL PAYMENT MANAGEMENT
    # ========================================================================

    def record_payment(self, payment_data: BillPaymentCreate, organization_id: str) -> BillPayment:
        """Record a payment against a bill"""
        payment_id = str(uuid.uuid4())

        # Get bill to validate payment amount and get vendor_id
        bill = self.get_bill(payment_data.bill_id)
        if not bill:
            raise ValueError(f"Bill {payment_data.bill_id} not found")

        if payment_data.amount > bill.balance_due:
            raise ValueError(f"Payment amount ${payment_data.amount} exceeds balance due ${bill.balance_due}")

        with sqlite3.connect(self.db_path) as conn:
            # Create payment record
            conn.execute("""
                INSERT INTO bill_payments (
                    payment_id, organization_id, vendor_id, bill_id,
                    payment_date, amount, payment_method, reference, notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                payment_id, organization_id, bill.vendor_id, payment_data.bill_id,
                payment_data.payment_date.isoformat(), str(payment_data.amount),
                payment_data.payment_method.value, payment_data.reference, payment_data.notes
            ))

            # Update bill amounts
            new_amount_paid = bill.amount_paid + payment_data.amount
            new_balance_due = bill.total - new_amount_paid

            # Determine new status
            if new_balance_due <= Decimal("0.01"):
                new_status = BillStatus.PAID
                paid_at = datetime.now().isoformat()
            elif new_amount_paid > 0:
                new_status = BillStatus.PARTIAL
                paid_at = None
            else:
                new_status = bill.status
                paid_at = None

            conn.execute("""
                UPDATE bills
                SET amount_paid = ?, balance_due = ?, status = ?, paid_at = ?, updated_at = datetime('now')
                WHERE bill_id = ?
            """, (str(new_amount_paid), str(new_balance_due), new_status.value, paid_at, payment_data.bill_id))

            conn.commit()

            # Create journal entry if bookkeeper is available
            if self.bookkeeper:
                updated_bill = self.get_bill(payment_data.bill_id)
                payment = BillPayment(
                    payment_id=payment_id,
                    organization_id=organization_id,
                    vendor_id=bill.vendor_id,
                    bill_id=payment_data.bill_id,
                    payment_date=payment_data.payment_date,
                    amount=payment_data.amount,
                    payment_method=payment_data.payment_method,
                    reference=payment_data.reference,
                    notes=payment_data.notes
                )
                self._create_payment_journal_entry(payment, updated_bill)

        return self.get_payment(payment_id)

    def get_payment(self, payment_id: str) -> Optional[BillPayment]:
        """Get payment by ID"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM bill_payments WHERE payment_id = ?
            """, (payment_id,))
            row = cursor.fetchone()

            if not row:
                return None

            return BillPayment(
                payment_id=row['payment_id'],
                organization_id=row['organization_id'],
                vendor_id=row['vendor_id'],
                bill_id=row['bill_id'],
                payment_date=date.fromisoformat(row['payment_date']),
                amount=Decimal(row['amount']),
                payment_method=PaymentMethod(row['payment_method']),
                reference=row['reference'],
                notes=row['notes'],
                created_at=datetime.fromisoformat(row['created_at'])
            )

    def list_payments(self, organization_id: str, bill_id: Optional[str] = None) -> List[BillPayment]:
        """List payments"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            query = "SELECT * FROM bill_payments WHERE organization_id = ?"
            params = [organization_id]

            if bill_id:
                query += " AND bill_id = ?"
                params.append(bill_id)

            query += " ORDER BY payment_date DESC"

            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

            return [
                BillPayment(
                    payment_id=row['payment_id'],
                    organization_id=row['organization_id'],
                    vendor_id=row['vendor_id'],
                    bill_id=row['bill_id'],
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

    def generate_ap_aging_report(self, organization_id: str, as_of_date: Optional[date] = None) -> APAgingReport:
        """Generate Accounts Payable Aging Report"""
        if not as_of_date:
            as_of_date = date.today()

        # Get all outstanding bills
        bills = self.list_bills(organization_id)
        outstanding_bills = [bill for bill in bills if bill.balance_due > 0 and bill.status != BillStatus.CANCELLED]

        # Initialize buckets
        buckets = {
            "current": APAgingBucket(bucket_name="Current (not yet due)"),
            "1_30": APAgingBucket(bucket_name="1-30 days past due"),
            "31_60": APAgingBucket(bucket_name="31-60 days past due"),
            "61_90": APAgingBucket(bucket_name="61-90 days past due"),
            "90_plus": APAgingBucket(bucket_name="90+ days past due")
        }

        # Categorize bills
        for bill in outstanding_bills:
            days_past_due = (as_of_date - bill.due_date).days

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

            bucket.bill_count += 1
            bucket.total_amount += bill.balance_due
            bucket.bills.append(bill)

        # Calculate totals
        report = APAgingReport(
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

    def generate_1099_report(self, organization_id: str, tax_year: int) -> Organization1099Summary:
        """Generate 1099 report for all vendors"""
        vendors = self.list_vendors(organization_id, active_only=False)
        vendor_reports = []

        for vendor in vendors:
            if not vendor.requires_1099:
                continue

            # Get all payments for this vendor in the tax year
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("""
                    SELECT
                        strftime('%m', payment_date) as month,
                        SUM(CAST(amount AS REAL)) as total
                    FROM bill_payments
                    WHERE vendor_id = ? AND strftime('%Y', payment_date) = ?
                    GROUP BY month
                    ORDER BY month
                """, (vendor.vendor_id, str(tax_year)))

                monthly_breakdown = [
                    {"month": row['month'], "amount": Decimal(str(row['total']))}
                    for row in cursor.fetchall()
                ]

                # Get total for year
                total_payments = sum(item['amount'] for item in monthly_breakdown)

                vendor_report = Vendor1099Report(
                    vendor_id=vendor.vendor_id,
                    vendor_name=vendor.name,
                    vendor_ein=vendor.ein,
                    tax_year=tax_year,
                    total_payments=total_payments,
                    requires_1099=vendor.requires_1099,
                    needs_filing=total_payments >= Decimal("600.00"),  # IRS threshold
                    payment_breakdown=monthly_breakdown
                )

                vendor_reports.append(vendor_report)

        vendors_requiring_filing = [v for v in vendor_reports if v.needs_filing]

        return Organization1099Summary(
            organization_id=organization_id,
            tax_year=tax_year,
            total_vendors=len(vendor_reports),
            vendors_requiring_1099=len(vendors_requiring_filing),
            total_1099_payments=sum(v.total_payments for v in vendors_requiring_filing),
            vendors=vendor_reports
        )

    # ========================================================================
    # JOURNAL ENTRY INTEGRATION
    # ========================================================================

    def _create_bill_journal_entry(self, bill: Bill):
        """Create journal entry when bill is recorded (Expense debit, A/P credit)"""
        if not self.bookkeeper:
            return

        # When bill is recorded:
        # Debit: Expense Account (from bill items)
        # Credit: Accounts Payable (2000)

        from app.bookkeeping.models import JournalEntry, JournalEntryLine

        lines = []

        # Create debit lines for each bill item
        for item in bill.items:
            account_id = item.account_id or "5900"  # Default to Other Expenses
            lines.append(JournalEntryLine(
                account_id=account_id,
                debit=item.amount,
                credit=Decimal("0.00"),
                memo=item.description
            ))

        # Create credit line for A/P
        lines.append(JournalEntryLine(
            account_id="2000",  # Accounts Payable
            debit=Decimal("0.00"),
            credit=bill.total,
            memo=f"Bill from vendor (Bill #{bill.bill_number or bill.bill_id})"
        ))

        entry = JournalEntry(
            entry_date=bill.bill_date,
            description=f"Bill recorded - {bill.bill_number or bill.bill_id}",
            reference=bill.bill_number or bill.bill_id,
            lines=lines
        )

        try:
            self.bookkeeper.create_journal_entry(entry)
            self.bookkeeper.post_journal_entry(entry.entry_id)
        except Exception as e:
            print(f"Warning: Failed to create journal entry for bill {bill.bill_id}: {e}")

    def _create_payment_journal_entry(self, payment: BillPayment, bill: Bill):
        """Create journal entry when bill payment is made (A/P debit, Cash credit)"""
        if not self.bookkeeper:
            return

        # When payment is made:
        # Debit: Accounts Payable (2000)
        # Credit: Cash/Bank Account (1000 or 1020)

        from app.bookkeeping.models import JournalEntry, JournalEntryLine

        # Determine cash account based on payment method
        cash_account = "1020"  # Business Checking Account
        if payment.payment_method == PaymentMethod.CASH:
            cash_account = "1000"  # Cash - Operating

        entry = JournalEntry(
            entry_date=payment.payment_date,
            description=f"Bill payment - {bill.bill_number or bill.bill_id}",
            reference=payment.reference or bill.bill_number or bill.bill_id,
            lines=[
                JournalEntryLine(
                    account_id="2000",  # Accounts Payable
                    debit=payment.amount,
                    credit=Decimal("0.00"),
                    memo=f"Payment for bill {bill.bill_number or bill.bill_id}"
                ),
                JournalEntryLine(
                    account_id=cash_account,
                    debit=Decimal("0.00"),
                    credit=payment.amount,
                    memo=f"Bill payment - {payment.payment_method.value}"
                )
            ]
        )

        try:
            self.bookkeeper.create_journal_entry(entry)
            self.bookkeeper.post_journal_entry(entry.entry_id)
        except Exception as e:
            print(f"Warning: Failed to create journal entry for payment {payment.payment_id}: {e}")
