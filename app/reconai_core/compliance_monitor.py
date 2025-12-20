import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import json
import re


class AlertSeverity(Enum):
    """Alert severity levels"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    VIOLATION = "violation"


@dataclass
class ComplianceAlert:
    """Compliance alert/warning"""
    severity: AlertSeverity
    category: str
    message: str
    regulation: str
    current_value: float
    threshold: float
    suggested_actions: List[str] = field(default_factory=list)
    documentation_needed: List[str] = field(default_factory=list)
    triggered_at: datetime = field(default_factory=datetime.now)


@dataclass
class PerDiemRate:
    """IRS per-diem rate for location"""
    location: str
    lodging: float
    meals: float
    incidentals: float
    total: float
    effective_date: str
    fiscal_year: int


class ComplianceMonitor:
    """
    Real-time compliance and regulatory monitoring system
    
    Monitors expenses against:
    - IRS regulations
    - Industry standards
    - Audit triggers
    - Documentation requirements
    """
    
    # IRS Per-Diem Rates (2024 - simplified, real implementation would fetch from GSA)
    PER_DIEM_RATES = {
        # High-cost locations
        "New York, NY": PerDiemRate("New York, NY", 312, 79, 5, 396, "2024-10-01", 2025),
        "San Francisco, CA": PerDiemRate("San Francisco, CA", 306, 79, 5, 390, "2024-10-01", 2025),
        "Washington, DC": PerDiemRate("Washington, DC", 251, 79, 5, 335, "2024-10-01", 2025),
        "Boston, MA": PerDiemRate("Boston, MA", 289, 79, 5, 373, "2024-10-01", 2025),
        "Seattle, WA": PerDiemRate("Seattle, WA", 247, 79, 5, 331, "2024-10-01", 2025),
        
        # Standard rate (everywhere else)
        "STANDARD": PerDiemRate("Standard", 107, 68, 5, 180, "2024-10-01", 2025)
    }
    
    # Mileage rates (2024)
    MILEAGE_RATES = {
        "business": 0.67,
        "medical": 0.21,
        "charity": 0.14
    }
    
    # Cash transaction reporting threshold
    CASH_REPORTING_THRESHOLD = 10000
    
    # Audit risk thresholds
    AUDIT_THRESHOLDS = {
        "meals_percent_of_revenue": 0.70,  # 70%+ triggers review
        "home_office_square_feet": 300,    # Excessive space
        "vehicle_business_use": 0.50,      # Must be >50%
        "round_number_percent": 0.40,      # Too many round numbers
        "cash_transaction_percent": 0.30,  # High cash usage
        "consecutive_loss_years": 2        # Hobby loss rule
    }
    
    def __init__(
        self,
        business_type: str = "Schedule C",
        primary_location: str = "STANDARD",
        enable_auto_fetch: bool = False
    ):
        """
        Initialize compliance monitor
        
        Args:
            business_type: Type of business entity
            primary_location: Primary business location for per-diem
            enable_auto_fetch: Auto-fetch current rates from GSA
        """
        self.business_type = business_type
        self.primary_location = primary_location
        self.alerts_history: List[ComplianceAlert] = []
        
        if enable_auto_fetch:
            self._fetch_current_rates()
    
    def _fetch_current_rates(self):
        """
        Fetch current per-diem rates from GSA
        In production, this would hit GSA API
        """
        # Placeholder - real implementation would use GSA PerDiem API
        # https://www.gsa.gov/travel/plan-book/per-diem-rates
        pass
    
    def check_per_diem(
        self, 
        expense_type: str,
        location: str,
        amount: float,
        date: datetime
    ) -> Optional[ComplianceAlert]:
        """
        Check if expense exceeds IRS per-diem limits
        
        Args:
            expense_type: "lodging", "meals", or "incidentals"
            location: City/state string
            amount: Amount spent
            date: Date of expense
        
        Returns:
            Alert if per-diem exceeded, None otherwise
        """
        
        # Get applicable per-diem rate
        rate = self.PER_DIEM_RATES.get(location, self.PER_DIEM_RATES["STANDARD"])
        
        # Get limit for expense type
        if expense_type.lower() == "lodging":
            limit = rate.lodging
        elif expense_type.lower() in ["meals", "food"]:
            limit = rate.meals
        elif expense_type.lower() == "incidentals":
            limit = rate.incidentals
        else:
            return None
        
        # Check if exceeded
        if amount > limit:
            excess = amount - limit
            percent_over = (excess / limit) * 100
            
            severity = (
                AlertSeverity.CRITICAL if percent_over > 50
                else AlertSeverity.WARNING
            )
            
            return ComplianceAlert(
                severity=severity,
                category="Per-Diem Limit",
                message=f"{expense_type.title()} expense ${amount:.2f} exceeds per-diem limit ${limit:.2f} for {location}",
                regulation=f"IRS Per-Diem Rates FY{rate.fiscal_year}",
                current_value=amount,
                threshold=limit,
                suggested_actions=[
                    f"Reduce to per-diem rate of ${limit:.2f}",
                    "Provide business justification for excess",
                    "Consider splitting stay across multiple locations",
                    "Document actual costs if higher than per-diem"
                ],
                documentation_needed=[
                    "Hotel receipt showing actual charges",
                    "Business purpose memo",
                    "Explanation of why per-diem insufficient"
                ]
            )
        
        return None
    
    def check_mileage(
        self,
        miles: float,
        date: datetime,
        purpose: str = "business"
    ) -> Dict:
        """
        Calculate mileage deduction and check for issues
        
        Returns:
            Dictionary with deduction amount and any alerts
        """
        
        rate = self.MILEAGE_RATES.get(purpose.lower(), self.MILEAGE_RATES["business"])
        deduction = miles * rate
        
        alerts = []
        
        # Check for excessive daily mileage
        if miles > 500:
            alerts.append(ComplianceAlert(
                severity=AlertSeverity.WARNING,
                category="Excessive Mileage",
                message=f"{miles} miles in single day exceeds typical business travel",
                regulation="IRS Mileage Documentation Requirements",
                current_value=miles,
                threshold=500,
                suggested_actions=[
                    "Verify odometer readings",
                    "Document trip purpose and route",
                    "Provide MapQuest/Google Maps route confirmation"
                ],
                documentation_needed=[
                    "Mileage log with date, destination, purpose",
                    "Route documentation",
                    "Business purpose memo"
                ]
            ))
        
        # Check for round numbers (potential estimate)
        if miles % 10 == 0 and miles > 50:
            alerts.append(ComplianceAlert(
                severity=AlertSeverity.INFO,
                category="Round Number Mileage",
                message=f"Mileage of {miles} is round number - ensure actual reading",
                regulation="IRS Substantiation Requirements",
                current_value=miles,
                threshold=0,
                suggested_actions=[
                    "Use actual odometer readings",
                    "Enable GPS mileage tracking",
                    "Keep contemporaneous records"
                ],
                documentation_needed=[
                    "Mileage tracking app records",
                    "Vehicle odometer photos"
                ]
            ))
        
        return {
            "deduction": deduction,
            "rate": rate,
            "miles": miles,
            "alerts": alerts
        }
    
    def check_cash_transaction(
        self,
        amount: float,
        description: str
    ) -> Optional[ComplianceAlert]:
        """
        Check cash transactions against reporting thresholds
        
        IRS requires Form 8300 for cash transactions $10K+
        """
        
        if amount >= self.CASH_REPORTING_THRESHOLD:
            return ComplianceAlert(
                severity=AlertSeverity.CRITICAL,
                category="Cash Reporting Required",
                message=f"Cash transaction ${amount:,.2f} requires IRS Form 8300 filing",
                regulation="31 USC 5331 - Cash Reporting",
                current_value=amount,
                threshold=self.CASH_REPORTING_THRESHOLD,
                suggested_actions=[
                    "File IRS Form 8300 within 15 days",
                    "Obtain payer identification",
                    "Document transaction details",
                    "Consider structuring compliance"
                ],
                documentation_needed=[
                    "Form 8300 (Report of Cash Payments)",
                    "Payer ID information",
                    "Transaction details and business purpose",
                    "Receipt of cash"
                ]
            )
        
        elif amount >= self.CASH_REPORTING_THRESHOLD * 0.90:
            # Close to threshold - warn
            return ComplianceAlert(
                severity=AlertSeverity.WARNING,
                category="Near Cash Reporting Threshold",
                message=f"Cash transaction ${amount:,.2f} near reporting threshold",
                regulation="31 USC 5331",
                current_value=amount,
                threshold=self.CASH_REPORTING_THRESHOLD,
                suggested_actions=[
                    "Be prepared to file Form 8300 if crosses $10K",
                    "Consider payment method change",
                    "Document business necessity of cash"
                ]
            )
        
        return None
    
    def check_meal_deduction_limits(
        self,
        ytd_expenses: pd.DataFrame
    ) -> List[ComplianceAlert]:
        """
        Check meal & entertainment deduction compliance
        
        Post-TCJA (2017):
        - 50% deductible for business meals
        - 0% for entertainment (no longer deductible)
        - 100% for meals provided to employees
        """
        
        alerts = []
        
        # Find meal expenses
        meals = ytd_expenses[
            ytd_expenses['category'].str.contains('Meal|Food|Restaurant', case=False, na=False)
        ]
        
        total_meals = meals['amount'].sum()
        
        # Check if entertainment misclassified as meals
        potential_entertainment = meals[
            meals['description'].str.contains(
                'concert|game|sporting|entertainment|theater|golf',
                case=False,
                na=False
            )
        ]
        
        if len(potential_entertainment) > 0:
            entertainment_amount = potential_entertainment['amount'].sum()
            
            alerts.append(ComplianceAlert(
                severity=AlertSeverity.CRITICAL,
                category="Entertainment Misclassification",
                message=f"${entertainment_amount:,.2f} in potential entertainment expenses classified as meals",
                regulation="TCJA 2017 - Entertainment Deduction Elimination",
                current_value=entertainment_amount,
                threshold=0,
                suggested_actions=[
                    "Reclassify entertainment expenses (0% deductible)",
                    "Keep only business meals (50% deductible)",
                    "Document food/beverage was primary purpose",
                    "Separate entertainment costs"
                ],
                documentation_needed=[
                    "Business purpose of meal",
                    "Business relationship of attendees",
                    "Proof meal was not lavish or extravagant"
                ]
            ))
        
        # Check for excessive meal percentage
        revenue = ytd_expenses.get('revenue', pd.Series([100000])).sum()
        if revenue > 0:
            meal_percent = total_meals / revenue
            
            if meal_percent > self.AUDIT_THRESHOLDS["meals_percent_of_revenue"]:
                alerts.append(ComplianceAlert(
                    severity=AlertSeverity.CRITICAL,
                    category="Excessive Meal Deductions",
                    message=f"Meal expenses {meal_percent:.1%} of revenue (audit risk >70%)",
                    regulation="IRS Audit Selection Criteria",
                    current_value=meal_percent,
                    threshold=self.AUDIT_THRESHOLDS["meals_percent_of_revenue"],
                    suggested_actions=[
                        "Review and remove personal meals",
                        "Ensure all meals have business purpose",
                        "Document business discussions",
                        "Keep detailed meal logs"
                    ],
                    documentation_needed=[
                        "Meal log with business purpose",
                        "List of attendees and business relationships",
                        "Topics discussed",
                        "All receipts"
                    ]
                ))
        
        return alerts
    
    def check_home_office(
        self,
        square_footage: float,
        home_total_sqft: float,
        business_use_percent: float
    ) -> List[ComplianceAlert]:
        """
        Check home office deduction compliance
        
        Requirements:
        - Exclusive use
        - Regular use
        - Principal place of business OR meeting clients
        """
        
        alerts = []
        
        # Check if space is excessive
        if square_footage > self.AUDIT_THRESHOLDS["home_office_square_feet"]:
            alerts.append(ComplianceAlert(
                severity=AlertSeverity.WARNING,
                category="Large Home Office",
                message=f"{square_footage} sq ft home office may trigger review",
                regulation="IRC Section 280A - Home Office",
                current_value=square_footage,
                threshold=self.AUDIT_THRESHOLDS["home_office_square_feet"],
                suggested_actions=[
                    "Ensure exclusive business use",
                    "Document regular business use",
                    "Take photos of space",
                    "Maintain visitor log if meeting clients"
                ],
                documentation_needed=[
                    "Floor plan showing office space",
                    "Photos of dedicated office",
                    "Business use log",
                    "Client meeting records (if applicable)"
                ]
            ))
        
        # Check business use percentage
        calculated_percent = (square_footage / home_total_sqft) if home_total_sqft > 0 else 0
        
        if abs(calculated_percent - business_use_percent) > 0.05:
            alerts.append(ComplianceAlert(
                severity=AlertSeverity.WARNING,
                category="Home Office Percentage Mismatch",
                message=f"Business use {business_use_percent:.1%} doesn't match calculated {calculated_percent:.1%}",
                regulation="IRS Home Office Calculation",
                current_value=business_use_percent,
                threshold=calculated_percent,
                suggested_actions=[
                    "Recalculate: office sqft / total sqft",
                    "Use actual measurements",
                    "Document calculation method"
                ]
            ))
        
        return alerts
    
    def check_vehicle_business_use(
        self,
        business_miles: float,
        total_miles: float
    ) -> Optional[ComplianceAlert]:
        """
        Check vehicle business use percentage
        
        Requirements:
        - Must be >50% business use to deduct
        - Need contemporaneous mileage log
        """
        
        if total_miles == 0:
            return None
        
        business_percent = business_miles / total_miles
        
        if business_percent <= self.AUDIT_THRESHOLDS["vehicle_business_use"]:
            return ComplianceAlert(
                severity=AlertSeverity.CRITICAL,
                category="Vehicle Business Use Below 50%",
                message=f"Business use {business_percent:.1%} ≤ 50% - cannot deduct vehicle expenses",
                regulation="IRC Section 280F - Vehicle Deduction Limits",
                current_value=business_percent,
                threshold=self.AUDIT_THRESHOLDS["vehicle_business_use"],
                suggested_actions=[
                    "Use actual expense method only if >50% business",
                    "Consider standard mileage instead",
                    "Document all business trips",
                    "Keep mileage log throughout year"
                ],
                documentation_needed=[
                    "Contemporaneous mileage log",
                    "Business purpose for each trip",
                    "Odometer readings",
                    "Vehicle ownership documents"
                ]
            )
        
        elif business_percent < 0.60:
            # Close to threshold
            return ComplianceAlert(
                severity=AlertSeverity.WARNING,
                category="Vehicle Business Use Near Threshold",
                message=f"Business use {business_percent:.1%} close to 50% minimum",
                regulation="IRC Section 280F",
                current_value=business_percent,
                threshold=0.50,
                suggested_actions=[
                    "Increase business mileage documentation",
                    "Review personal vs business trips",
                    "Consider dedicated business vehicle"
                ]
            )
        
        return None
    
    def generate_compliance_report(
        self,
        ytd_expenses: pd.DataFrame
    ) -> Dict:
        """
        Generate comprehensive compliance report
        
        Returns:
            Dictionary with all compliance checks and alerts
        """
        
        alerts = []
        
        # Run all compliance checks
        
        # 1. Meal deduction limits
        alerts.extend(self.check_meal_deduction_limits(ytd_expenses))
        
        # 2. Cash transactions
        cash_expenses = ytd_expenses[
            ytd_expenses.get('payment_type', '') == 'cash'
        ]
        for _, expense in cash_expenses.iterrows():
            alert = self.check_cash_transaction(
                expense['amount'],
                expense.get('description', '')
            )
            if alert:
                alerts.append(alert)
        
        # 3. Round number analysis
        amounts = ytd_expenses['amount'].values
        round_numbers = sum(1 for amt in amounts if amt % 10 == 0)
        round_percent = round_numbers / len(amounts) if len(amounts) > 0 else 0
        
        if round_percent > self.AUDIT_THRESHOLDS["round_number_percent"]:
            alerts.append(ComplianceAlert(
                severity=AlertSeverity.WARNING,
                category="Excessive Round Numbers",
                message=f"{round_percent:.1%} of expenses are round numbers",
                regulation="IRS Substantiation Requirements",
                current_value=round_percent,
                threshold=self.AUDIT_THRESHOLDS["round_number_percent"],
                suggested_actions=[
                    "Use actual receipt amounts",
                    "Avoid estimating expenses",
                    "Sync with bank statements",
                    "Document any legitimate round amounts"
                ]
            ))
        
        # Categorize alerts by severity
        critical = [a for a in alerts if a.severity == AlertSeverity.CRITICAL]
        warnings = [a for a in alerts if a.severity == AlertSeverity.WARNING]
        info = [a for a in alerts if a.severity == AlertSeverity.INFO]
        
        return {
            "report_date": datetime.now().isoformat(),
            "total_alerts": len(alerts),
            "critical_count": len(critical),
            "warning_count": len(warnings),
            "info_count": len(info),
            "alerts": {
                "critical": [self._alert_to_dict(a) for a in critical],
                "warnings": [self._alert_to_dict(a) for a in warnings],
                "info": [self._alert_to_dict(a) for a in info]
            },
            "compliance_score": self._calculate_compliance_score(alerts),
            "recommendations": self._generate_recommendations(alerts)
        }
    
    def _alert_to_dict(self, alert: ComplianceAlert) -> Dict:
        """Convert alert to dictionary"""
        return {
            "severity": alert.severity.value,
            "category": alert.category,
            "message": alert.message,
            "regulation": alert.regulation,
            "current_value": alert.current_value,
            "threshold": alert.threshold,
            "suggested_actions": alert.suggested_actions,
            "documentation_needed": alert.documentation_needed
        }
    
    def _calculate_compliance_score(self, alerts: List[ComplianceAlert]) -> float:
        """
        Calculate compliance score (0-100)
        
        100 = perfect compliance
        0 = major violations
        """
        if not alerts:
            return 100.0
        
        # Weight by severity
        penalty = 0
        for alert in alerts:
            if alert.severity == AlertSeverity.CRITICAL:
                penalty += 25
            elif alert.severity == AlertSeverity.WARNING:
                penalty += 10
            elif alert.severity == AlertSeverity.INFO:
                penalty += 2
        
        score = max(0, 100 - penalty)
        return score
    
    def _generate_recommendations(self, alerts: List[ComplianceAlert]) -> List[str]:
        """Generate prioritized recommendations"""
        
        if not alerts:
            return ["✅ No compliance issues detected"]
        
        recommendations = []
        
        # Critical items first
        critical = [a for a in alerts if a.severity == AlertSeverity.CRITICAL]
        if critical:
            recommendations.append(
                f"🔴 URGENT: Address {len(critical)} critical compliance issues immediately"
            )
            for alert in critical[:3]:  # Top 3
                recommendations.append(f"  → {alert.category}: {alert.suggested_actions[0]}")
        
        # Warnings
        warnings = [a for a in alerts if a.severity == AlertSeverity.WARNING]
        if warnings:
            recommendations.append(
                f"⚠️  Review {len(warnings)} warning items before year-end"
            )
        
        return recommendations