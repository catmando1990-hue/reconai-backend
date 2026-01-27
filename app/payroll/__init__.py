# app/payroll/__init__.py
"""
Payroll Domain — Write-Enabled, Audit-Critical

DOMAIN RULES:
- Payroll is WRITE-ENABLED (draft → approved → locked)
- CFO is READ-ONLY (consumes snapshots)
- DCAA is SEALED and SNAPSHOT-ONLY
- Payroll NEVER calls DCAA or CFO directly
- Every mutation is audit-logged with before/after values
- Snapshots are immutable, hash-sealed, versioned
"""
