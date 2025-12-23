# app/tax_intelligence/__init__.py

from app.tax_intelligence.models import (
    TaxEstimate,
    QuarterlyTaxPayment,
    DeductionCategory,
    DeductionOptimization,
    TaxDeadline,
    TaxCalendar,
    StateFilingRequirement,
    TaxProjection,
)
from app.tax_intelligence.engine import TaxIntelligenceEngine

__all__ = [
    "TaxEstimate",
    "QuarterlyTaxPayment",
    "DeductionCategory",
    "DeductionOptimization",
    "TaxDeadline",
    "TaxCalendar",
    "StateFilingRequirement",
    "TaxProjection",
    "TaxIntelligenceEngine",
]
