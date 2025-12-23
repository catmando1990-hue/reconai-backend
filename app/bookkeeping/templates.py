# app/bookkeeping/templates.py

"""
Standard Chart of Accounts templates for different business types.
"""

from decimal import Decimal
from .models import Account, AccountType, AccountSubtype, NormalBalance, NORMAL_BALANCE_MAP


def get_standard_chart_of_accounts() -> dict:
    """
    Get a standard chart of accounts for a small business (Schedule C / sole proprietor).

    Account numbering convention:
    - 1000-1999: Assets
    - 2000-2999: Liabilities
    - 3000-3999: Equity
    - 4000-4999: Revenue
    - 5000-5999: Expenses (Operating)
    - 6000-6999: Expenses (Cost of Goods Sold)
    - 7000-7999: Other Income/Expenses
    """
    accounts = [
        # ASSETS (1000-1999)
        {
            "account_id": "1000",
            "account_number": "1000",
            "account_name": "Cash - Operating",
            "account_type": "Asset",
            "account_subtype": "Cash",
            "description": "Primary operating cash account",
            "normal_balance": "Debit"
        },
        {
            "account_id": "1010",
            "account_number": "1010",
            "account_name": "Cash - Savings",
            "account_type": "Asset",
            "account_subtype": "Cash",
            "description": "Business savings account",
            "normal_balance": "Debit"
        },
        {
            "account_id": "1020",
            "account_number": "1020",
            "account_name": "Business Checking Account",
            "account_type": "Asset",
            "account_subtype": "Bank",
            "description": "Primary business checking",
            "normal_balance": "Debit"
        },
        {
            "account_id": "1200",
            "account_number": "1200",
            "account_name": "Accounts Receivable",
            "account_type": "Asset",
            "account_subtype": "Accounts Receivable",
            "description": "Money owed by customers",
            "normal_balance": "Debit"
        },
        {
            "account_id": "1300",
            "account_number": "1300",
            "account_name": "Inventory",
            "account_type": "Asset",
            "account_subtype": "Inventory",
            "description": "Products held for sale",
            "normal_balance": "Debit"
        },
        {
            "account_id": "1400",
            "account_number": "1400",
            "account_name": "Prepaid Expenses",
            "account_type": "Asset",
            "account_subtype": "Prepaid Expenses",
            "description": "Expenses paid in advance",
            "normal_balance": "Debit"
        },
        {
            "account_id": "1500",
            "account_number": "1500",
            "account_name": "Equipment",
            "account_type": "Asset",
            "account_subtype": "Fixed Assets",
            "description": "Business equipment and machinery",
            "normal_balance": "Debit"
        },
        {
            "account_id": "1510",
            "account_number": "1510",
            "account_name": "Vehicles",
            "account_type": "Asset",
            "account_subtype": "Fixed Assets",
            "description": "Business vehicles",
            "normal_balance": "Debit"
        },
        {
            "account_id": "1520",
            "account_number": "1520",
            "account_name": "Furniture & Fixtures",
            "account_type": "Asset",
            "account_subtype": "Fixed Assets",
            "description": "Office furniture and fixtures",
            "normal_balance": "Debit"
        },
        {
            "account_id": "1600",
            "account_number": "1600",
            "account_name": "Accumulated Depreciation",
            "account_type": "Asset",
            "account_subtype": "Accumulated Depreciation",
            "description": "Contra-asset account for depreciation",
            "normal_balance": "Credit"
        },

        # LIABILITIES (2000-2999)
        {
            "account_id": "2000",
            "account_number": "2000",
            "account_name": "Accounts Payable",
            "account_type": "Liability",
            "account_subtype": "Accounts Payable",
            "description": "Money owed to vendors/suppliers",
            "normal_balance": "Credit"
        },
        {
            "account_id": "2100",
            "account_number": "2100",
            "account_name": "Credit Card - Business",
            "account_type": "Liability",
            "account_subtype": "Credit Card",
            "description": "Business credit card payable",
            "normal_balance": "Credit"
        },
        {
            "account_id": "2200",
            "account_number": "2200",
            "account_name": "Loan Payable - Short-term",
            "account_type": "Liability",
            "account_subtype": "Loans Payable",
            "description": "Loans due within 1 year",
            "normal_balance": "Credit"
        },
        {
            "account_id": "2300",
            "account_number": "2300",
            "account_name": "Loan Payable - Long-term",
            "account_type": "Liability",
            "account_subtype": "Long-term Liabilities",
            "description": "Loans due after 1 year",
            "normal_balance": "Credit"
        },
        {
            "account_id": "2400",
            "account_number": "2400",
            "account_name": "Accrued Expenses",
            "account_type": "Liability",
            "account_subtype": "Accrued Expenses",
            "description": "Expenses incurred but not yet paid",
            "normal_balance": "Credit"
        },
        {
            "account_id": "2500",
            "account_number": "2500",
            "account_name": "Deferred Revenue",
            "account_type": "Liability",
            "account_subtype": "Deferred Revenue",
            "description": "Revenue received but not yet earned",
            "normal_balance": "Credit"
        },

        # EQUITY (3000-3999)
        {
            "account_id": "3000",
            "account_number": "3000",
            "account_name": "Owner's Equity",
            "account_type": "Equity",
            "account_subtype": "Owners_Equity",
            "description": "Owner's investment in business",
            "normal_balance": "Credit"
        },
        {
            "account_id": "3100",
            "account_number": "3100",
            "account_name": "Retained Earnings",
            "account_type": "Equity",
            "account_subtype": "Retained Earnings",
            "description": "Accumulated profits retained in business",
            "normal_balance": "Credit"
        },
        {
            "account_id": "3200",
            "account_number": "3200",
            "account_name": "Owner Draws",
            "account_type": "Equity",
            "account_subtype": "Draws",
            "description": "Money taken out by owner",
            "normal_balance": "Debit"
        },

        # REVENUE (4000-4999)
        {
            "account_id": "4000",
            "account_number": "4000",
            "account_name": "Service Revenue",
            "account_type": "Revenue",
            "account_subtype": "Service Revenue",
            "description": "Income from services provided",
            "normal_balance": "Credit"
        },
        {
            "account_id": "4100",
            "account_number": "4100",
            "account_name": "Product Sales",
            "account_type": "Revenue",
            "account_subtype": "Sales Revenue",
            "description": "Income from product sales",
            "normal_balance": "Credit"
        },
        {
            "account_id": "4200",
            "account_number": "4200",
            "account_name": "Consulting Revenue",
            "account_type": "Revenue",
            "account_subtype": "Service Revenue",
            "description": "Income from consulting services",
            "normal_balance": "Credit"
        },
        {
            "account_id": "4900",
            "account_number": "4900",
            "account_name": "Other Income",
            "account_type": "Revenue",
            "account_subtype": "Other Income",
            "description": "Miscellaneous income",
            "normal_balance": "Credit"
        },

        # COST OF GOODS SOLD (6000-6999)
        {
            "account_id": "6000",
            "account_number": "6000",
            "account_name": "Cost of Goods Sold",
            "account_type": "Expense",
            "account_subtype": "Cost of Goods Sold",
            "description": "Direct costs of products sold",
            "normal_balance": "Debit"
        },
        {
            "account_id": "6100",
            "account_number": "6100",
            "account_name": "Materials & Supplies",
            "account_type": "Expense",
            "account_subtype": "Cost of Goods Sold",
            "description": "Raw materials and supplies",
            "normal_balance": "Debit"
        },

        # OPERATING EXPENSES (5000-5999)
        {
            "account_id": "5000",
            "account_number": "5000",
            "account_name": "Advertising & Marketing",
            "account_type": "Expense",
            "account_subtype": "Operating Expenses",
            "description": "Marketing and advertising costs (Schedule C Line 8)",
            "normal_balance": "Debit"
        },
        {
            "account_id": "5010",
            "account_number": "5010",
            "account_name": "Vehicle Expenses",
            "account_type": "Expense",
            "account_subtype": "Operating Expenses",
            "description": "Car and truck expenses (Schedule C Line 9)",
            "normal_balance": "Debit"
        },
        {
            "account_id": "5020",
            "account_number": "5020",
            "account_name": "Commissions & Fees",
            "account_type": "Expense",
            "account_subtype": "Operating Expenses",
            "description": "Commissions and fees (Schedule C Line 10)",
            "normal_balance": "Debit"
        },
        {
            "account_id": "5030",
            "account_number": "5030",
            "account_name": "Insurance",
            "account_type": "Expense",
            "account_subtype": "Insurance Expense",
            "description": "Business insurance (Schedule C Line 15)",
            "normal_balance": "Debit"
        },
        {
            "account_id": "5040",
            "account_number": "5040",
            "account_name": "Legal & Professional Services",
            "account_type": "Expense",
            "account_subtype": "Operating Expenses",
            "description": "Legal and professional services (Schedule C Line 17)",
            "normal_balance": "Debit"
        },
        {
            "account_id": "5050",
            "account_number": "5050",
            "account_name": "Office Expenses",
            "account_type": "Expense",
            "account_subtype": "Operating Expenses",
            "description": "Office expense (Schedule C Line 18)",
            "normal_balance": "Debit"
        },
        {
            "account_id": "5060",
            "account_number": "5060",
            "account_name": "Rent - Office",
            "account_type": "Expense",
            "account_subtype": "Rent Expense",
            "description": "Rent or lease (Schedule C Line 20b)",
            "normal_balance": "Debit"
        },
        {
            "account_id": "5070",
            "account_number": "5070",
            "account_name": "Repairs & Maintenance",
            "account_type": "Expense",
            "account_subtype": "Operating Expenses",
            "description": "Repairs and maintenance (Schedule C Line 21)",
            "normal_balance": "Debit"
        },
        {
            "account_id": "5080",
            "account_number": "5080",
            "account_name": "Supplies",
            "account_type": "Expense",
            "account_subtype": "Operating Expenses",
            "description": "Supplies (Schedule C Line 22)",
            "normal_balance": "Debit"
        },
        {
            "account_id": "5090",
            "account_number": "5090",
            "account_name": "Taxes & Licenses",
            "account_type": "Expense",
            "account_subtype": "Tax Expense",
            "description": "Taxes and licenses (Schedule C Line 23)",
            "normal_balance": "Debit"
        },
        {
            "account_id": "5100",
            "account_number": "5100",
            "account_name": "Travel - Airfare",
            "account_type": "Expense",
            "account_subtype": "Operating Expenses",
            "description": "Travel airfare (Schedule C Line 24a)",
            "normal_balance": "Debit"
        },
        {
            "account_id": "5110",
            "account_number": "5110",
            "account_name": "Travel - Lodging",
            "account_type": "Expense",
            "account_subtype": "Operating Expenses",
            "description": "Travel lodging (Schedule C Line 24a)",
            "normal_balance": "Debit"
        },
        {
            "account_id": "5120",
            "account_number": "5120",
            "account_name": "Meals & Entertainment",
            "account_type": "Expense",
            "account_subtype": "Operating Expenses",
            "description": "Meals (50% deductible) (Schedule C Line 24b)",
            "normal_balance": "Debit"
        },
        {
            "account_id": "5130",
            "account_number": "5130",
            "account_name": "Utilities",
            "account_type": "Expense",
            "account_subtype": "Utilities Expense",
            "description": "Utilities (Schedule C Line 25)",
            "normal_balance": "Debit"
        },
        {
            "account_id": "5140",
            "account_number": "5140",
            "account_name": "Wages & Contractor Payments",
            "account_type": "Expense",
            "account_subtype": "Payroll Expenses",
            "description": "Wages and contractor payments (Schedule C Line 26)",
            "normal_balance": "Debit"
        },
        {
            "account_id": "5900",
            "account_number": "5900",
            "account_name": "Other Expenses",
            "account_type": "Expense",
            "account_subtype": "Other Expenses",
            "description": "Other expenses (Schedule C Line 27)",
            "normal_balance": "Debit"
        },

        # OTHER INCOME/EXPENSES (7000-7999)
        {
            "account_id": "7000",
            "account_number": "7000",
            "account_name": "Interest Income",
            "account_type": "Revenue",
            "account_subtype": "Interest Income",
            "description": "Interest earned on bank accounts",
            "normal_balance": "Credit"
        },
        {
            "account_id": "7100",
            "account_number": "7100",
            "account_name": "Interest Expense",
            "account_type": "Expense",
            "account_subtype": "Interest Expense",
            "description": "Interest paid on loans/credit cards",
            "normal_balance": "Debit"
        },
        {
            "account_id": "7200",
            "account_number": "7200",
            "account_name": "Depreciation Expense",
            "account_type": "Expense",
            "account_subtype": "Depreciation Expense",
            "description": "Depreciation of fixed assets",
            "normal_balance": "Debit"
        },
    ]

    return {
        "template_name": "Standard Chart of Accounts - Small Business",
        "template_version": "1.0",
        "description": "Standard chart of accounts for Schedule C sole proprietors and small businesses",
        "total_accounts": len(accounts),
        "accounts": accounts,
        "usage_instructions": [
            "Import these accounts using POST /api/bookkeeping/accounts/bulk-import",
            "Customize account names and descriptions as needed",
            "Add sub-accounts by setting parent_account_id",
            "Account numbers can be customized to fit your business"
        ],
        "account_ranges": {
            "1000-1999": "Assets",
            "2000-2999": "Liabilities",
            "3000-3999": "Equity",
            "4000-4999": "Revenue",
            "5000-5999": "Operating Expenses",
            "6000-6999": "Cost of Goods Sold",
            "7000-7999": "Other Income/Expenses"
        }
    }
