# app/reconai_core/bank_parsers.py
"""
ReconAI Bank-Specific Parsers
Specialized parsing logic for major US banks
"""

import re
from datetime import date, datetime
from typing import List, Optional, Tuple
from app.models import Transaction
from app.reconai_core.bank_intelligence import BankProfile


# ============================================================================
# CHASE BANK PARSERS
# ============================================================================

def parse_chase_statement(text: str, profile: BankProfile) -> Tuple[List[Transaction], List[str]]:
    """
    Parse Chase bank statements.
    
    Chase format typically:
    Date        Description                     Amount      Balance
    12/15/2025  WALMART #1234                  -52.18      1,234.56
    12/14/2025  DEPOSIT                        500.00      1,286.74
    """
    notes = [f"Using Chase-specific parser"]
    txs: List[Transaction] = []
    
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    
    # Chase date pattern: MM/DD/YYYY or MM/DD/YY
    date_pattern = re.compile(r'^(\d{1,2}/\d{1,2}/\d{2,4})\s+(.+?)(?:\s+(-?\$?\d{1,3}(?:,\d{3})*(?:\.\d{2})))\s*(?:\$?\d{1,3}(?:,\d{3})*(?:\.\d{2}))?$')
    
    for line in lines:
        match = date_pattern.match(line)
        if match:
            date_str, description, amount_str = match.groups()
            
            # Parse date
            try:
                if len(date_str.split('/')[-1]) == 2:
                    tx_date = datetime.strptime(date_str, "%m/%d/%y").date()
                else:
                    tx_date = datetime.strptime(date_str, "%m/%d/%Y").date()
            except:
                continue
            
            # Parse amount
            amount = _parse_amount(amount_str)
            if amount is None:
                continue
            
            merchant = _merchant_guess(description)
            
            txs.append(Transaction(
                date=tx_date,
                amount=float(amount),
                description=description.strip(),
                merchant=merchant,
                classification=None,
                reason=None
            ))
    
    if txs:
        notes.append(f"Extracted {len(txs)} transactions from Chase statement")
    else:
        notes.append("No transactions matched Chase format. May need format adjustment.")
    
    return txs, notes


# ============================================================================
# BANK OF AMERICA PARSERS
# ============================================================================

def parse_bofa_statement(text: str, profile: BankProfile) -> Tuple[List[Transaction], List[str]]:
    """
    Parse Bank of America statements.
    
    BofA format typically:
    Date        Description                     Amount      Running Bal.
    12/15       STARBUCKS #12345               -5.47       1,234.56
    12/14       Online Transfer                 500.00     1,740.03
    """
    notes = [f"Using Bank of America-specific parser"]
    txs: List[Transaction] = []
    
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    
    # BofA often uses MM/DD format (year inferred from statement period)
    date_pattern = re.compile(r'^(\d{1,2}/\d{1,2}(?:/\d{2,4})?)\s+(.+?)(?:\s+(-?\$?\d{1,3}(?:,\d{3})*(?:\.\d{2})))\s*(?:\$?\d{1,3}(?:,\d{3})*(?:\.\d{2}))?$')
    
    # Try to find statement period year from header
    current_year = datetime.now().year
    year_match = re.search(r'Statement Period.*?(\d{4})', text, re.IGNORECASE)
    if year_match:
        current_year = int(year_match.group(1))
    
    for line in lines:
        match = date_pattern.match(line)
        if match:
            date_str, description, amount_str = match.groups()
            
            # Parse date
            try:
                if '/' in date_str and len(date_str.split('/')) == 2:
                    # Add year
                    tx_date = datetime.strptime(f"{date_str}/{current_year}", "%m/%d/%Y").date()
                elif len(date_str.split('/')[-1]) == 2:
                    tx_date = datetime.strptime(date_str, "%m/%d/%y").date()
                else:
                    tx_date = datetime.strptime(date_str, "%m/%d/%Y").date()
            except:
                continue
            
            amount = _parse_amount(amount_str)
            if amount is None:
                continue
            
            merchant = _merchant_guess(description)
            
            txs.append(Transaction(
                date=tx_date,
                amount=float(amount),
                description=description.strip(),
                merchant=merchant,
                classification=None,
                reason=None
            ))
    
    if txs:
        notes.append(f"Extracted {len(txs)} transactions from Bank of America statement")
    else:
        notes.append("No transactions matched BofA format. May need format adjustment.")
    
    return txs, notes


# ============================================================================
# WELLS FARGO PARSERS
# ============================================================================

def parse_wells_fargo_statement(text: str, profile: BankProfile) -> Tuple[List[Transaction], List[str]]:
    """
    Parse Wells Fargo statements.
    
    Wells Fargo format typically:
    Date        Check No.   Description             Withdrawals     Deposits    Balance
    12/15/25                AMAZON.COM              52.18                       1,234.56
    12/14/25                PAYCHECK                            2,000.00        1,786.74
    """
    notes = [f"Using Wells Fargo-specific parser"]
    txs: List[Transaction] = []
    
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    
    # Wells Fargo can use various date formats
    # Pattern matches: date, optional check number, description, and amount columns
    date_pattern = re.compile(
        r'^(\d{1,2}/\d{1,2}/\d{2,4})\s+(?:\d+\s+)?(.+?)\s+(?:(-?\$?\d{1,3}(?:,\d{3})*(?:\.\d{2}))\s+)?(?:(-?\$?\d{1,3}(?:,\d{3})*(?:\.\d{2}))\s+)?(?:\$?\d{1,3}(?:,\d{3})*(?:\.\d{2}))?$'
    )
    
    for line in lines:
        match = date_pattern.match(line)
        if match:
            date_str, description, withdrawal, deposit = match.groups()
            
            # Parse date
            try:
                if len(date_str.split('/')[-1]) == 2:
                    tx_date = datetime.strptime(date_str, "%m/%d/%y").date()
                else:
                    tx_date = datetime.strptime(date_str, "%m/%d/%Y").date()
            except:
                continue
            
            # Amount is either withdrawal (negative) or deposit (positive)
            amount_str = withdrawal or deposit
            if not amount_str:
                continue
            
            amount = _parse_amount(amount_str)
            if amount is None:
                continue
            
            # If it was in withdrawal column, make it negative
            if withdrawal and amount > 0:
                amount = -amount
            
            merchant = _merchant_guess(description)
            
            txs.append(Transaction(
                date=tx_date,
                amount=float(amount),
                description=description.strip(),
                merchant=merchant,
                classification=None,
                reason=None
            ))
    
    if txs:
        notes.append(f"Extracted {len(txs)} transactions from Wells Fargo statement")
    else:
        notes.append("No transactions matched Wells Fargo format. May need format adjustment.")
    
    return txs, notes


# ============================================================================
# CAPITAL ONE PARSERS
# ============================================================================

def parse_capital_one_statement(text: str, profile: BankProfile) -> Tuple[List[Transaction], List[str]]:
    """
    Parse Capital One statements (both banking and credit card).
    
    Capital One format typically:
    Transaction Date    Posted Date     Description                 Debit       Credit
    2025-12-15         2025-12-16      WHOLE FOODS #123            52.18
    2025-12-14         2025-12-15      PAYMENT - THANK YOU                     500.00
    """
    notes = [f"Using Capital One-specific parser"]
    txs: List[Transaction] = []
    
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    
    # Capital One often uses YYYY-MM-DD format
    date_pattern = re.compile(
        r'^(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4})\s+(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}\s+)?(.+?)\s+(?:(-?\$?\d{1,3}(?:,\d{3})*(?:\.\d{2}))\s+)?(?:(-?\$?\d{1,3}(?:,\d{3})*(?:\.\d{2})))?$'
    )
    
    for line in lines:
        match = date_pattern.match(line)
        if match:
            date_str, description, debit, credit = match.groups()
            
            # Parse date
            try:
                if '-' in date_str:
                    tx_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                elif len(date_str.split('/')[-1]) == 2:
                    tx_date = datetime.strptime(date_str, "%m/%d/%y").date()
                else:
                    tx_date = datetime.strptime(date_str, "%m/%d/%Y").date()
            except:
                continue
            
            # Amount is either debit (negative) or credit (positive)
            amount_str = debit or credit
            if not amount_str:
                continue
            
            amount = _parse_amount(amount_str)
            if amount is None:
                continue
            
            # If it was a debit, make it negative
            if debit and amount > 0:
                amount = -amount
            
            merchant = _merchant_guess(description)
            
            txs.append(Transaction(
                date=tx_date,
                amount=float(amount),
                description=description.strip(),
                merchant=merchant,
                classification=None,
                reason=None
            ))
    
    if txs:
        notes.append(f"Extracted {len(txs)} transactions from Capital One statement")
    else:
        notes.append("No transactions matched Capital One format. May need format adjustment.")
    
    return txs, notes


# ============================================================================
# USAA PARSERS
# ============================================================================

def parse_usaa_statement(text: str, profile: BankProfile) -> Tuple[List[Transaction], List[str]]:
    """
    Parse USAA statements.
    
    USAA format typically similar to other banks:
    Date        Description                     Amount      Balance
    12/15/2025  COSTCO WHSE #1234              -125.43     2,345.67
    """
    notes = [f"Using USAA-specific parser"]
    txs: List[Transaction] = []
    
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    
    date_pattern = re.compile(r'^(\d{1,2}/\d{1,2}/\d{2,4})\s+(.+?)(?:\s+(-?\$?\d{1,3}(?:,\d{3})*(?:\.\d{2})))\s*(?:\$?\d{1,3}(?:,\d{3})*(?:\.\d{2}))?$')
    
    for line in lines:
        match = date_pattern.match(line)
        if match:
            date_str, description, amount_str = match.groups()
            
            try:
                if len(date_str.split('/')[-1]) == 2:
                    tx_date = datetime.strptime(date_str, "%m/%d/%y").date()
                else:
                    tx_date = datetime.strptime(date_str, "%m/%d/%Y").date()
            except:
                continue
            
            amount = _parse_amount(amount_str)
            if amount is None:
                continue
            
            merchant = _merchant_guess(description)
            
            txs.append(Transaction(
                date=tx_date,
                amount=float(amount),
                description=description.strip(),
                merchant=merchant,
                classification=None,
                reason=None
            ))
    
    if txs:
        notes.append(f"Extracted {len(txs)} transactions from USAA statement")
    else:
        notes.append("No transactions matched USAA format. May need format adjustment.")
    
    return txs, notes


# ============================================================================
# DISCOVER PARSERS
# ============================================================================

def parse_discover_statement(text: str, profile: BankProfile) -> Tuple[List[Transaction], List[str]]:
    """
    Parse Discover credit card statements.
    
    Discover format typically:
    Trans Date  Post Date   Description                 Amount      Category
    12/15/25    12/16/25    AMAZON.COM                 52.18       Shopping
    """
    notes = [f"Using Discover-specific parser"]
    txs: List[Transaction] = []
    
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    
    # Discover uses trans date and post date
    date_pattern = re.compile(
        r'^(\d{1,2}/\d{1,2}/\d{2,4})\s+\d{1,2}/\d{1,2}/\d{2,4}\s+(.+?)\s+(-?\$?\d{1,3}(?:,\d{3})*(?:\.\d{2}))\s*(?:\w+)?$'
    )
    
    for line in lines:
        match = date_pattern.match(line)
        if match:
            date_str, description, amount_str = match.groups()
            
            try:
                if len(date_str.split('/')[-1]) == 2:
                    tx_date = datetime.strptime(date_str, "%m/%d/%y").date()
                else:
                    tx_date = datetime.strptime(date_str, "%m/%d/%Y").date()
            except:
                continue
            
            amount = _parse_amount(amount_str)
            if amount is None:
                continue
            
            # Credit card charges are typically shown as positive but are debits
            if amount > 0:
                amount = -amount
            
            merchant = _merchant_guess(description)
            
            txs.append(Transaction(
                date=tx_date,
                amount=float(amount),
                description=description.strip(),
                merchant=merchant,
                classification=None,
                reason=None
            ))
    
    if txs:
        notes.append(f"Extracted {len(txs)} transactions from Discover statement")
    else:
        notes.append("No transactions matched Discover format. May need format adjustment.")
    
    return txs, notes


# ============================================================================
# AMERICAN EXPRESS PARSERS
# ============================================================================

def parse_amex_statement(text: str, profile: BankProfile) -> Tuple[List[Transaction], List[str]]:
    """
    Parse American Express credit card statements.
    
    AmEx format can vary but typically:
    Date        Description                     Amount
    12/15/25    WHOLE FOODS MARKET #123        $52.18
    12/14/25    UBER *TRIP                     $18.45
    """
    notes = [f"Using American Express-specific parser"]
    txs: List[Transaction] = []
    
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    
    date_pattern = re.compile(r'^(\d{1,2}/\d{1,2}/\d{2,4})\s+(.+?)\s+\$?(-?\d{1,3}(?:,\d{3})*(?:\.\d{2}))$')
    
    for line in lines:
        match = date_pattern.match(line)
        if match:
            date_str, description, amount_str = match.groups()
            
            try:
                if len(date_str.split('/')[-1]) == 2:
                    tx_date = datetime.strptime(date_str, "%m/%d/%y").date()
                else:
                    tx_date = datetime.strptime(date_str, "%m/%d/%Y").date()
            except:
                continue
            
            amount = _parse_amount(amount_str)
            if amount is None:
                continue
            
            # AmEx charges are typically shown as positive but are debits
            if amount > 0:
                amount = -amount
            
            merchant = _merchant_guess(description)
            
            txs.append(Transaction(
                date=tx_date,
                amount=float(amount),
                description=description.strip(),
                merchant=merchant,
                classification=None,
                reason=None
            ))
    
    if txs:
        notes.append(f"Extracted {len(txs)} transactions from American Express statement")
    else:
        notes.append("No transactions matched AmEx format. May need format adjustment.")
    
    return txs, notes


# ============================================================================
# PARSER ROUTER
# ============================================================================

BANK_PARSER_MAP = {
    "Chase": parse_chase_statement,
    "Bank of America": parse_bofa_statement,
    "Wells Fargo": parse_wells_fargo_statement,
    "Capital One": parse_capital_one_statement,
    "USAA": parse_usaa_statement,
    "Discover Bank": parse_discover_statement,
    "American Express": parse_amex_statement,
}


def get_parser_for_bank(bank_name: str):
    """Get the appropriate parser function for a bank"""
    return BANK_PARSER_MAP.get(bank_name)