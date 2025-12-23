# app/bookkeeping/engine.py

from __future__ import annotations
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional, Dict
import sqlite3
from pathlib import Path

from .models import (
    Account,
    AccountType,
    AccountSubtype,
    NormalBalance,
    NORMAL_BALANCE_MAP,
    JournalEntry,
    JournalEntryLine,
    AccountBalance,
    TrialBalance,
    GeneralLedger,
    GeneralLedgerEntry
)


class BookkeeperEngine:
    """
    Double-entry bookkeeping engine.

    Implements:
    - Chart of Accounts management
    - Journal entry processing with validation
    - Account balance calculations
    - Trial balance generation
    - General ledger queries
    """

    def __init__(self, db_path: str | Path):
        """
        Initialize bookkeeper engine with database.

        Args:
            db_path: Path to SQLite database
        """
        self.db_path = Path(db_path)
        self._init_database()

    def _init_database(self):
        """Create database tables if they don't exist"""
        with sqlite3.connect(self.db_path) as conn:
            # Chart of Accounts table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS accounts (
                    account_id TEXT PRIMARY KEY,
                    account_number TEXT NOT NULL UNIQUE,
                    account_name TEXT NOT NULL,
                    account_type TEXT NOT NULL,
                    account_subtype TEXT,
                    description TEXT,
                    normal_balance TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    parent_account_id TEXT,
                    current_balance TEXT DEFAULT '0.00',
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (parent_account_id) REFERENCES accounts(account_id)
                )
            """)

            # Journal Entries table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS journal_entries (
                    entry_id TEXT PRIMARY KEY,
                    entry_number TEXT UNIQUE,
                    entry_date TEXT NOT NULL,
                    description TEXT NOT NULL,
                    reference TEXT,
                    status TEXT DEFAULT 'draft',
                    created_by TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    posted_at TEXT,
                    voided_at TEXT
                )
            """)

            # Journal Entry Lines table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS journal_entry_lines (
                    line_id TEXT PRIMARY KEY,
                    entry_id TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    debit TEXT DEFAULT '0.00',
                    credit TEXT DEFAULT '0.00',
                    memo TEXT,
                    line_order INTEGER,
                    FOREIGN KEY (entry_id) REFERENCES journal_entries(entry_id),
                    FOREIGN KEY (account_id) REFERENCES accounts(account_id)
                )
            """)

            # Create indexes for performance
            conn.execute("CREATE INDEX IF NOT EXISTS idx_accounts_type ON accounts(account_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_accounts_active ON accounts(is_active)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_entries_date ON journal_entries(entry_date)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_entries_status ON journal_entries(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_lines_account ON journal_entry_lines(account_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_lines_entry ON journal_entry_lines(entry_id)")

            conn.commit()

    # =========================================================================
    # CHART OF ACCOUNTS - CRUD OPERATIONS
    # =========================================================================

    def create_account(self, account: Account) -> Account:
        """
        Create a new account in the chart of accounts.

        Args:
            account: Account object to create

        Returns:
            Created account

        Raises:
            ValueError: If account_id or account_number already exists
        """
        with sqlite3.connect(self.db_path) as conn:
            try:
                conn.execute("""
                    INSERT INTO accounts (
                        account_id, account_number, account_name, account_type,
                        account_subtype, description, normal_balance, is_active,
                        parent_account_id, current_balance
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    account.account_id,
                    account.account_number,
                    account.account_name,
                    account.account_type.value,
                    account.account_subtype.value if account.account_subtype else None,
                    account.description,
                    account.normal_balance.value,
                    1 if account.is_active else 0,
                    account.parent_account_id,
                    str(account.current_balance)
                ))
                conn.commit()
                return account
            except sqlite3.IntegrityError as e:
                raise ValueError(f"Account with ID '{account.account_id}' or number '{account.account_number}' already exists")

    def get_account(self, account_id: str) -> Optional[Account]:
        """
        Get account by ID.

        Args:
            account_id: Account identifier

        Returns:
            Account object or None if not found
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM accounts WHERE account_id = ?",
                (account_id,)
            )
            row = cursor.fetchone()

            if row:
                return Account(
                    account_id=row['account_id'],
                    account_number=row['account_number'],
                    account_name=row['account_name'],
                    account_type=AccountType(row['account_type']),
                    account_subtype=AccountSubtype(row['account_subtype']) if row['account_subtype'] else None,
                    description=row['description'],
                    normal_balance=NormalBalance(row['normal_balance']),
                    is_active=bool(row['is_active']),
                    parent_account_id=row['parent_account_id'],
                    current_balance=Decimal(row['current_balance']),
                    created_at=datetime.fromisoformat(row['created_at']),
                    updated_at=datetime.fromisoformat(row['updated_at'])
                )
            return None

    def list_accounts(
        self,
        account_type: Optional[AccountType] = None,
        active_only: bool = True
    ) -> List[Account]:
        """
        List all accounts, optionally filtered by type.

        Args:
            account_type: Filter by account type
            active_only: Only return active accounts

        Returns:
            List of accounts
        """
        query = "SELECT * FROM accounts WHERE 1=1"
        params = []

        if account_type:
            query += " AND account_type = ?"
            params.append(account_type.value)

        if active_only:
            query += " AND is_active = 1"

        query += " ORDER BY account_number"

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)
            accounts = []

            for row in cursor.fetchall():
                accounts.append(Account(
                    account_id=row['account_id'],
                    account_number=row['account_number'],
                    account_name=row['account_name'],
                    account_type=AccountType(row['account_type']),
                    account_subtype=AccountSubtype(row['account_subtype']) if row['account_subtype'] else None,
                    description=row['description'],
                    normal_balance=NormalBalance(row['normal_balance']),
                    is_active=bool(row['is_active']),
                    parent_account_id=row['parent_account_id'],
                    current_balance=Decimal(row['current_balance']),
                    created_at=datetime.fromisoformat(row['created_at']),
                    updated_at=datetime.fromisoformat(row['updated_at'])
                ))

            return accounts

    def update_account(self, account_id: str, updates: Dict) -> Optional[Account]:
        """
        Update an existing account.

        Args:
            account_id: Account to update
            updates: Dictionary of fields to update

        Returns:
            Updated account or None if not found
        """
        allowed_fields = {
            'account_name', 'account_type', 'account_subtype',
            'description', 'is_active', 'parent_account_id'
        }

        # Filter to allowed fields
        updates = {k: v for k, v in updates.items() if k in allowed_fields}

        if not updates:
            return self.get_account(account_id)

        # Build UPDATE query
        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
        set_clause += ", updated_at = datetime('now')"
        values = list(updates.values()) + [account_id]

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"UPDATE accounts SET {set_clause} WHERE account_id = ?",
                values
            )
            conn.commit()

        return self.get_account(account_id)

    def delete_account(self, account_id: str, force: bool = False) -> bool:
        """
        Delete an account (soft delete by default).

        Args:
            account_id: Account to delete
            force: If True, hard delete. If False, soft delete (set inactive)

        Returns:
            True if deleted, False if not found

        Raises:
            ValueError: If account has transactions and force=False
        """
        # Check if account has transactions
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM journal_entry_lines WHERE account_id = ?",
                (account_id,)
            )
            count = cursor.fetchone()[0]

            if count > 0 and not force:
                raise ValueError(
                    f"Account {account_id} has {count} transactions. "
                    "Use force=True to hard delete or soft delete by setting is_active=False"
                )

            if force:
                # Hard delete
                conn.execute("DELETE FROM accounts WHERE account_id = ?", (account_id,))
            else:
                # Soft delete
                conn.execute(
                    "UPDATE accounts SET is_active = 0, updated_at = datetime('now') WHERE account_id = ?",
                    (account_id,)
                )

            conn.commit()
            return conn.total_changes > 0

    # =========================================================================
    # JOURNAL ENTRIES - CREATE & VALIDATE
    # =========================================================================

    def create_journal_entry(self, entry: JournalEntry, auto_post: bool = False) -> JournalEntry:
        """
        Create a new journal entry.

        Args:
            entry: Journal entry to create
            auto_post: If True, automatically post the entry

        Returns:
            Created journal entry with entry_id

        Raises:
            ValueError: If entry validation fails
        """
        # Validate entry
        is_valid, errors = entry.validate_entry()
        if not is_valid:
            raise ValueError(f"Invalid journal entry: {'; '.join(errors)}")

        # Validate all accounts exist
        for line in entry.lines:
            if not self.get_account(line.account_id):
                raise ValueError(f"Account {line.account_id} does not exist")

        # Generate entry_id if not provided
        if not entry.entry_id:
            entry.entry_id = self._generate_entry_id()

        # Generate entry_number if not provided
        if not entry.entry_number:
            entry.entry_number = self._generate_entry_number(entry.entry_date)

        with sqlite3.connect(self.db_path) as conn:
            # Insert journal entry
            conn.execute("""
                INSERT INTO journal_entries (
                    entry_id, entry_number, entry_date, description,
                    reference, status, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                entry.entry_id,
                entry.entry_number,
                entry.entry_date.isoformat(),
                entry.description,
                entry.reference,
                entry.status,
                entry.created_by,
                entry.created_at.isoformat()
            ))

            # Insert journal entry lines
            for i, line in enumerate(entry.lines):
                line_id = line.line_id or f"{entry.entry_id}-L{i+1}"
                conn.execute("""
                    INSERT INTO journal_entry_lines (
                        line_id, entry_id, account_id, debit, credit, memo, line_order
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    line_id,
                    entry.entry_id,
                    line.account_id,
                    str(line.debit),
                    str(line.credit),
                    line.memo,
                    i
                ))

            conn.commit()

        # Auto-post if requested
        if auto_post:
            entry = self.post_journal_entry(entry.entry_id)

        return entry

    def post_journal_entry(self, entry_id: str) -> JournalEntry:
        """
        Post a journal entry (update account balances).

        Args:
            entry_id: Entry to post

        Returns:
            Posted journal entry

        Raises:
            ValueError: If entry not found or already posted
        """
        entry = self.get_journal_entry(entry_id)
        if not entry:
            raise ValueError(f"Entry {entry_id} not found")

        if entry.status == "posted":
            raise ValueError(f"Entry {entry_id} is already posted")

        if entry.status == "voided":
            raise ValueError(f"Entry {entry_id} is voided and cannot be posted")

        # Re-validate before posting
        is_valid, errors = entry.validate_entry()
        if not is_valid:
            raise ValueError(f"Cannot post invalid entry: {'; '.join(errors)}")

        with sqlite3.connect(self.db_path) as conn:
            # Update account balances
            for line in entry.lines:
                account = self.get_account(line.account_id)
                if not account:
                    raise ValueError(f"Account {line.account_id} not found")

                # Calculate new balance based on normal balance
                if account.normal_balance == NormalBalance.DEBIT:
                    # Debit increases, credit decreases
                    new_balance = account.current_balance + line.debit - line.credit
                else:  # CREDIT
                    # Credit increases, debit decreases
                    new_balance = account.current_balance + line.credit - line.debit

                conn.execute("""
                    UPDATE accounts
                    SET current_balance = ?, updated_at = datetime('now')
                    WHERE account_id = ?
                """, (str(new_balance), line.account_id))

            # Mark entry as posted
            conn.execute("""
                UPDATE journal_entries
                SET status = 'posted', posted_at = datetime('now')
                WHERE entry_id = ?
            """, (entry_id,))

            conn.commit()

        # Return updated entry
        return self.get_journal_entry(entry_id)

    def void_journal_entry(self, entry_id: str, create_reversing_entry: bool = True) -> Optional[JournalEntry]:
        """
        Void a journal entry.

        Args:
            entry_id: Entry to void
            create_reversing_entry: If True, create a reversing entry

        Returns:
            Reversing entry if created, None otherwise

        Raises:
            ValueError: If entry not found or not posted
        """
        entry = self.get_journal_entry(entry_id)
        if not entry:
            raise ValueError(f"Entry {entry_id} not found")

        if entry.status != "posted":
            raise ValueError(f"Only posted entries can be voided")

        with sqlite3.connect(self.db_path) as conn:
            # Mark original entry as voided
            conn.execute("""
                UPDATE journal_entries
                SET status = 'voided', voided_at = datetime('now')
                WHERE entry_id = ?
            """, (entry_id,))
            conn.commit()

        reversing_entry = None

        if create_reversing_entry:
            # Create reversing entry (swap debits and credits)
            reversed_lines = []
            for line in entry.lines:
                reversed_lines.append(JournalEntryLine(
                    account_id=line.account_id,
                    debit=line.credit,  # Swap
                    credit=line.debit,  # Swap
                    memo=f"Reversal of {entry.entry_number}: {line.memo or ''}"
                ))

            reversing_entry = JournalEntry(
                entry_date=date.today(),
                description=f"REVERSAL of {entry.entry_number}: {entry.description}",
                reference=f"REV-{entry.entry_number}",
                lines=reversed_lines,
                status="draft"
            )

            reversing_entry = self.create_journal_entry(reversing_entry, auto_post=True)

        return reversing_entry

    def get_journal_entry(self, entry_id: str) -> Optional[JournalEntry]:
        """Get journal entry by ID with all lines"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Get entry header
            cursor = conn.execute(
                "SELECT * FROM journal_entries WHERE entry_id = ?",
                (entry_id,)
            )
            entry_row = cursor.fetchone()

            if not entry_row:
                return None

            # Get entry lines
            cursor = conn.execute(
                """SELECT jel.*, a.account_name
                   FROM journal_entry_lines jel
                   JOIN accounts a ON jel.account_id = a.account_id
                   WHERE jel.entry_id = ?
                   ORDER BY jel.line_order""",
                (entry_id,)
            )
            lines = []
            for line_row in cursor.fetchall():
                lines.append(JournalEntryLine(
                    line_id=line_row['line_id'],
                    account_id=line_row['account_id'],
                    account_name=line_row['account_name'],
                    debit=Decimal(line_row['debit']),
                    credit=Decimal(line_row['credit']),
                    memo=line_row['memo']
                ))

            return JournalEntry(
                entry_id=entry_row['entry_id'],
                entry_number=entry_row['entry_number'],
                entry_date=date.fromisoformat(entry_row['entry_date']),
                description=entry_row['description'],
                reference=entry_row['reference'],
                lines=lines,
                status=entry_row['status'],
                created_by=entry_row['created_by'],
                created_at=datetime.fromisoformat(entry_row['created_at']),
                posted_at=datetime.fromisoformat(entry_row['posted_at']) if entry_row['posted_at'] else None
            )

    def list_journal_entries(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        status: Optional[str] = None
    ) -> List[JournalEntry]:
        """List journal entries with optional filters"""
        query = "SELECT entry_id FROM journal_entries WHERE 1=1"
        params = []

        if start_date:
            query += " AND entry_date >= ?"
            params.append(start_date.isoformat())

        if end_date:
            query += " AND entry_date <= ?"
            params.append(end_date.isoformat())

        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY entry_date DESC, entry_number DESC"

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(query, params)
            entry_ids = [row[0] for row in cursor.fetchall()]

        return [self.get_journal_entry(eid) for eid in entry_ids]

    # =========================================================================
    # BALANCE CALCULATIONS & REPORTS
    # =========================================================================

    def get_account_balance(self, account_id: str) -> Decimal:
        """Get current balance for an account"""
        account = self.get_account(account_id)
        return account.current_balance if account else Decimal("0.00")

    def get_trial_balance(self, as_of_date: Optional[date] = None) -> TrialBalance:
        """
        Generate trial balance report.

        Args:
            as_of_date: Date for trial balance (defaults to today)

        Returns:
            Trial balance with all account balances
        """
        if not as_of_date:
            as_of_date = date.today()

        accounts = self.list_accounts(active_only=True)
        account_balances = []
        total_debits = Decimal("0.00")
        total_credits = Decimal("0.00")

        for account in accounts:
            # For trial balance, show balance on the normal side
            if account.normal_balance == NormalBalance.DEBIT:
                debit_balance = max(account.current_balance, Decimal("0.00"))
                credit_balance = Decimal("0.00")
            else:
                debit_balance = Decimal("0.00")
                credit_balance = max(account.current_balance, Decimal("0.00"))

            account_balances.append(AccountBalance(
                account_id=account.account_id,
                account_number=account.account_number,
                account_name=account.account_name,
                account_type=account.account_type,
                debit_balance=debit_balance,
                credit_balance=credit_balance,
                net_balance=account.current_balance,
                normal_balance=account.normal_balance
            ))

            total_debits += debit_balance
            total_credits += credit_balance

        is_balanced = total_debits == total_credits
        difference = total_debits - total_credits

        return TrialBalance(
            as_of_date=as_of_date,
            accounts=account_balances,
            total_debits=total_debits,
            total_credits=total_credits,
            is_balanced=is_balanced,
            difference=difference
        )

    def get_general_ledger(
        self,
        account_id: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> GeneralLedger:
        """
        Get general ledger for a specific account.

        Args:
            account_id: Account to get ledger for
            start_date: Start date filter
            end_date: End date filter

        Returns:
            General ledger with all entries
        """
        account = self.get_account(account_id)
        if not account:
            raise ValueError(f"Account {account_id} not found")

        query = """
            SELECT je.entry_id, je.entry_number, je.entry_date, je.description, je.reference,
                   jel.debit, jel.credit
            FROM journal_entry_lines jel
            JOIN journal_entries je ON jel.entry_id = je.entry_id
            WHERE jel.account_id = ? AND je.status = 'posted'
        """
        params = [account_id]

        if start_date:
            query += " AND je.entry_date >= ?"
            params.append(start_date.isoformat())

        if end_date:
            query += " AND je.entry_date <= ?"
            params.append(end_date.isoformat())

        query += " ORDER BY je.entry_date, je.entry_number"

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)

            entries = []
            running_balance = Decimal("0.00")

            for row in cursor.fetchall():
                debit = Decimal(row['debit'])
                credit = Decimal(row['credit'])

                # Update running balance based on normal balance
                if account.normal_balance == NormalBalance.DEBIT:
                    running_balance += debit - credit
                else:
                    running_balance += credit - debit

                entries.append(GeneralLedgerEntry(
                    entry_id=row['entry_id'],
                    entry_number=row['entry_number'],
                    entry_date=date.fromisoformat(row['entry_date']),
                    description=row['description'],
                    reference=row['reference'],
                    debit=debit,
                    credit=credit,
                    balance=running_balance
                ))

        return GeneralLedger(
            account=account,
            entries=entries,
            opening_balance=Decimal("0.00"),
            closing_balance=running_balance,
            period_start=start_date,
            period_end=end_date
        )

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def _generate_entry_id(self) -> str:
        """Generate unique entry ID"""
        import uuid
        return f"JE-{uuid.uuid4().hex[:12].upper()}"

    def _generate_entry_number(self, entry_date: date) -> str:
        """Generate human-readable entry number (e.g., JE-2024-001)"""
        year = entry_date.year

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT COUNT(*) FROM journal_entries
                WHERE entry_number LIKE ?
            """, (f"JE-{year}-%",))
            count = cursor.fetchone()[0] + 1

        return f"JE-{year}-{count:04d}"

    def validate_debit_credit_rule(self, account_id: str, debit: Decimal, credit: Decimal) -> tuple[bool, str]:
        """
        Validate debit/credit against account's normal balance.

        Returns:
            (is_valid, message)
        """
        if debit > 0 and credit > 0:
            return False, "A line cannot have both debit and credit"

        if debit == 0 and credit == 0:
            return False, "A line must have either debit or credit"

        if debit < 0 or credit < 0:
            return False, "Debit and credit amounts must be non-negative"

        return True, "Valid"
