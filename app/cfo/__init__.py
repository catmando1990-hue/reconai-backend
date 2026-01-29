# app/cfo/__init__.py
"""
CFO / Financial Controls Module (Phase 3)

Read-only financial analytics:
- Cash flow rollups (monthly/quarterly)
- Burn rate calculation
- Forecast projections with confidence gating
- Financial exception detection

CFO Data Isolation:
- Separate data silo for CFO tier (cfo_accounts, cfo_transactions, etc.)
- No cross-tier data access (CFO never reads core_transactions)

CANONICAL LAWS:
- No auto-refresh
- No background jobs
- Projections ≠ facts (explicit labeling)
- Confidence < 0.85 flagged
"""

from app.cfo.engine import CFOEngine
from app.cfo.models import (
    CashFlowRollup,
    BurnRateMetrics,
    ForecastProjection,
    FinancialException,
    CFOOverviewResponse,
    ForecastResponse,
    ExceptionsResponse,
)
from app.cfo import db

__all__ = [
    "CFOEngine",
    "CashFlowRollup",
    "BurnRateMetrics",
    "ForecastProjection",
    "FinancialException",
    "CFOOverviewResponse",
    "ForecastResponse",
    "ExceptionsResponse",
    "db",
]
