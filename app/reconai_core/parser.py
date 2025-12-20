# app/reconai_core/parser.py
"""
Generic transaction parser utilities.
Used by brain.py and other modules to parse CSV, text, and structured data.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from app.models import Transaction


@dataclass
class ParsedInput:
    """Result of parsing raw input text into transactions."""
    transactions: List[Transaction]
    notes: List[str]


def _parse_amount(s: str) -> Optional[Decimal]:
    """
    Parse an amount string into a Decimal.
    Handles formats like: $1,234.56, (1234.56), -$1234.56, etc.
    """
    if not s:
        return None
    
    # Remove whitespace
    s = s.strip()
    
    # Check for parentheses (negative)
    is_negative = s.startswith('(') and s.endswith(')')
    if is_negative:
        s = s[1:-1].strip()
    
    # Remove currency symbols and commas
    s = s.replace('$', '').replace(',', '').strip()
    
    # Check for negative sign
    if s.startswith('-'):
        is_negative = True
        s = s[1:].strip()
    
    try:
        amount = Decimal(s)
        return -amount if is_negative else amount
    except Exception:
        return None


def _parse_date(s: str) -> Optional[date]:
    """
    Attempt to parse a date string.
    Tries common formats: YYYY-MM-DD, MM/DD/YYYY, MM/DD/YY, etc.
    """
    if not s:
        return None
    
    s = s.strip()
    
    formats = [
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%d/%m/%Y",
        "%d/%m/%y",
        "%Y/%m/%d",
        "%b %d, %Y",
        "%B %d, %Y",
        "%d-%b-%Y",
        "%d-%B-%Y",
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            continue
    
    return None


def _merchant_guess(description: str) -> Optional[str]:
    """
    Extract a merchant name from a transaction description.
    This is a simple heuristic - just takes the first few words.
    """
    if not description:
        return None
    
    # Clean up
    desc = description.strip()
    
    # Remove common prefixes
    prefixes = ['POS', 'DEBIT', 'CREDIT', 'PAYMENT', 'TRANSFER', 'CHECK']
    for prefix in prefixes:
        if desc.upper().startswith(prefix):
            desc = desc[len(prefix):].strip()
    
    # Take first 3-5 words as merchant
    words = desc.split()[:5]
    merchant = ' '.join(words)
    
    # Remove transaction IDs (numbers at end)
    merchant = re.sub(r'\s+\d+$', '', merchant)
    
    return merchant if merchant else None


def parse_csv_text(text: str) -> ParsedInput:
    """
    Parse CSV-formatted transaction data.
    
    Expected format:
    date,description,amount
    or
    date,merchant,description,amount
    or similar variations
    """
    notes: List[str] = []
    transactions: List[Transaction] = []
    
    if not text or not text.strip():
        notes.append("Empty CSV input")
        return ParsedInput(transactions=[], notes=notes)
    
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    
    if not lines:
        notes.append("No valid lines in CSV")
        return ParsedInput(transactions=[], notes=notes)
    
    # Skip header if it looks like a header
    start_idx = 0
    first_line = lines[0].lower()
    if any(word in first_line for word in ['date', 'amount', 'description', 'merchant']):
        start_idx = 1
        notes.append("Detected CSV header, skipping first line")
    
    for i, line in enumerate(lines[start_idx:], start=start_idx + 1):
        parts = [p.strip() for p in line.split(',')]
        
        if len(parts) < 2:
            continue
        
        # Try to find date and amount
        tx_date: Optional[date] = None
        tx_amount: Optional[Decimal] = None
        tx_description = ""
        tx_merchant: Optional[str] = None
        
        # Common patterns:
        # date,description,amount
        # date,merchant,description,amount
        # date,amount,description
        
        for part in parts:
            if tx_date is None:
                parsed_date = _parse_date(part)
                if parsed_date:
                    tx_date = parsed_date
                    continue
            
            if tx_amount is None:
                parsed_amount = _parse_amount(part)
                if parsed_amount is not None:
                    tx_amount = parsed_amount
                    continue
            
            # Otherwise it's probably description
            if tx_description:
                tx_description += " " + part
            else:
                tx_description = part
        
        if tx_amount is None:
            notes.append(f"Line {i}: Could not parse amount, skipping")
            continue
        
        if not tx_date:
            tx_date = date.today()
            notes.append(f"Line {i}: No date found, using today")
        
        if not tx_description:
            tx_description = "Transaction"
        
        tx_merchant = _merchant_guess(tx_description)
        
        transactions.append(Transaction(
            date=tx_date,
            amount=float(tx_amount),
            description=tx_description,
            merchant=tx_merchant,
            classification=None,
            reason=None,
        ))
    
    notes.append(f"Parsed {len(transactions)} transactions from CSV")
    return ParsedInput(transactions=transactions, notes=notes)


def parse_text_lines(text: str) -> ParsedInput:
    """
    Generic text parser - tries to extract transactions from unstructured text.
    Looks for patterns like: date ... amount
    """
    notes: List[str] = ["Using generic text line parser"]
    transactions: List[Transaction] = []
    
    if not text or not text.strip():
        notes.append("Empty text input")
        return ParsedInput(transactions=[], notes=notes)
    
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    
    for line in lines:
        # Look for amount pattern
        amount_match = re.search(r'[\$\(]?\s*-?\s*\d{1,3}(?:,\d{3})*(?:\.\d{2})?\s*[\)]?', line)
        if not amount_match:
            continue
        
        amount_str = amount_match.group()
        amount = _parse_amount(amount_str)
        
        if amount is None:
            continue
        
        # Look for date
        tx_date: Optional[date] = None
        for word in line.split():
            parsed_date = _parse_date(word)
            if parsed_date:
                tx_date = parsed_date
                break
        
        # Description is everything except the amount
        description = line.replace(amount_str, '').strip()
        if not description:
            description = "Transaction"
        
        merchant = _merchant_guess(description)
        
        transactions.append(Transaction(
            date=tx_date or date.today(),
            amount=float(amount),
            description=description,
            merchant=merchant,
            classification=None,
            reason=None,
        ))
    
    if transactions:
        notes.append(f"Extracted {len(transactions)} transactions from text")
    else:
        notes.append("No transactions matched generic text patterns")
    
    return ParsedInput(transactions=transactions, notes=notes)


def parse_structured_transactions(txs: List[Transaction]) -> ParsedInput:
    """
    'Parse' already-structured transactions (from bank_pdf parsers, etc).
    This is a pass-through that just validates and returns.
    """
    notes: List[str] = [f"Using pre-structured transaction data ({len(txs)} transactions)"]
    
    # Could add validation here
    valid_txs = []
    for tx in txs:
        if tx.amount is None:
            continue
        valid_txs.append(tx)
    
    if len(valid_txs) < len(txs):
        notes.append(f"Filtered out {len(txs) - len(valid_txs)} invalid transactions")
    
    return ParsedInput(transactions=valid_txs, notes=notes)