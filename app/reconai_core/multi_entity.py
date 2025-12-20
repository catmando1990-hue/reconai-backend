import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from decimal import Decimal


class EntityType(Enum):
    """Business entity types"""
    SCHEDULE_C = "schedule_c"  # Sole proprietor
    SMLLC = "single_member_llc"  # Single-member LLC (disregarded)
    MMLLC = "multi_member_llc"  # Multi-member LLC (partnership)
    S_CORP = "s_corp"  # S-Corporation
    PARTNERSHIP = "partnership"  # General/Limited Partnership
    C_CORP = "c_corp"  # C-Corporation


@dataclass
class Owner:
    """Business owner/partner/shareholder"""
    name: str
    ownership_percent: float  # 0.0 to 1.0
    initial_capital: float = 0.0
    capital_account: float = 0.0
    basis: float = 0.0  # Tax basis
    distributions_ytd: float = 0.0
    guaranteed_payments: float = 0.0  # For partnerships
    w2_wages: float = 0.0  # For S-Corps
    
    def __post_init__(self):
        self.capital_account = self.initial_capital
        self.basis = self.initial_capital


@dataclass
class Transaction:
    """Entity transaction"""
    date: datetime
    type: str  # "income", "expense", "distribution", "contribution"
    amount: float
    category: str
    description: str
    owner: Optional[str] = None  # For owner-specific transactions
    personal: bool = False  # Personal vs business


@dataclass
class AllocationResult:
    """Income/loss allocation result"""
    owner: str
    ownership_percent: float
    allocated_income: float
    allocated_loss: float
    guaranteed_payments: float
    net_allocation: float
    ending_capital: float
    ending_basis: float


class MultiEntityManager:
    """
    Multi-entity financial intelligence system
    
    Handles complex entity structures:
    - Tracks ownership interests
    - Calculates allocations
    - Manages capital accounts
    - Prepares K-1 data
    - Optimizes distributions
    """
    
    # Reasonable compensation guidelines (by industry, simplified)
    REASONABLE_COMP_RANGES = {
        "professional_services": (80000, 200000),
        "technology": (100000, 250000),
        "healthcare": (120000, 300000),
        "retail": (50000, 150000),
        "manufacturing": (70000, 180000),
        "construction": (60000, 150000),
        "default": (60000, 150000)
    }
    
    def __init__(
        self,
        entity_type: str,
        entity_name: str,
        owners: List[Dict],
        fiscal_year_end: str = "12-31",
        industry: str = "default"
    ):
        """
        Initialize multi-entity manager
        
        Args:
            entity_type: Type of entity (s_corp, partnership, etc)
            entity_name: Legal entity name
            owners: List of owner dictionaries with name, ownership, etc
            fiscal_year_end: "MM-DD" format
            industry: Industry for reasonable compensation calc
        """
        
        self.entity_type = EntityType(entity_type.lower())
        self.entity_name = entity_name
        self.industry = industry
        
        # Parse fiscal year
        month, day = map(int, fiscal_year_end.split('-'))
        current_year = datetime.now().year
        self.fiscal_year_end = datetime(current_year, month, day)
        
        # Initialize owners
        self.owners: Dict[str, Owner] = {}
        for owner_data in owners:
            owner = Owner(
                name=owner_data['name'],
                ownership_percent=owner_data.get('ownership', 0.0),
                initial_capital=owner_data.get('initial_capital', 0.0),
                guaranteed_payments=owner_data.get('guaranteed_payments', 0.0),
                w2_wages=owner_data.get('w2_wages', 0.0)
            )
            self.owners[owner.name] = owner
        
        # Validate ownership adds to 100%
        total_ownership = sum(o.ownership_percent for o in self.owners.values())
        if not (0.99 <= total_ownership <= 1.01):
            raise ValueError(f"Total ownership {total_ownership:.1%} must equal 100%")
        
        # Transaction history
        self.transactions: List[Transaction] = []
        
        # Year-to-date totals
        self.ytd_income = 0.0
        self.ytd_expenses = 0.0
        self.ytd_distributions = 0.0
    
    def record_transaction(
        self,
        transaction_type: str,
        amount: float,
        category: str,
        description: str,
        date: Optional[datetime] = None,
        owner: Optional[str] = None,
        personal: bool = False
    ):
        """Record a transaction"""
        
        txn = Transaction(
            date=date or datetime.now(),
            type=transaction_type,
            amount=amount,
            category=category,
            description=description,
            owner=owner,
            personal=personal
        )
        
        self.transactions.append(txn)
        
        # Update YTD totals
        if transaction_type == "income":
            self.ytd_income += amount
        elif transaction_type == "expense" and not personal:
            self.ytd_expenses += amount
        elif transaction_type == "distribution":
            self.ytd_distributions += amount
            if owner and owner in self.owners:
                self.owners[owner].distributions_ytd += amount
    
    def classify_expense_type(
        self,
        expense: Dict
    ) -> Tuple[bool, str]:
        """
        Determine if expense is business or personal
        
        Returns:
            (is_business, reasoning)
        """
        
        description = expense.get('description', '').lower()
        category = expense.get('category', '').lower()
        
        # Clear business expenses
        business_keywords = [
            'office', 'equipment', 'software', 'marketing',
            'advertising', 'professional', 'insurance', 'rent'
        ]
        
        if any(kw in category or kw in description for kw in business_keywords):
            return True, "Clear business expense"
        
        # Clear personal expenses
        personal_keywords = [
            'grocery', 'personal', 'clothing', 'gym',
            'entertainment', 'vacation', 'home improvement'
        ]
        
        if any(kw in category or kw in description for kw in personal_keywords):
            return False, "Personal expense"
        
        # Ambiguous - need context
        ambiguous = [
            'meal', 'travel', 'vehicle', 'phone', 'internet'
        ]
        
        if any(kw in category or kw in description for kw in ambiguous):
            return True, "Potentially business - requires documentation"
        
        # Default to business but flag for review
        return True, "Assumed business - verify classification"
    
    def calculate_allocations(
        self,
        net_income: float
    ) -> List[AllocationResult]:
        """
        Calculate income/loss allocations to owners
        
        Different rules for:
        - S-Corps: Pro-rata by stock ownership
        - Partnerships: Can have special allocations
        - LLCs: Per operating agreement
        """
        
        results = []
        
        if self.entity_type == EntityType.S_CORP:
            # S-Corps must allocate pro-rata by ownership
            for name, owner in self.owners.items():
                allocated = net_income * owner.ownership_percent
                
                # Update capital account
                owner.capital_account += allocated
                owner.capital_account -= owner.distributions_ytd
                
                # Update basis
                owner.basis += allocated
                owner.basis -= owner.distributions_ytd
                
                results.append(AllocationResult(
                    owner=name,
                    ownership_percent=owner.ownership_percent,
                    allocated_income=max(0, allocated),
                    allocated_loss=abs(min(0, allocated)),
                    guaranteed_payments=0,  # S-Corps don't have guaranteed payments
                    net_allocation=allocated,
                    ending_capital=owner.capital_account,
                    ending_basis=owner.basis
                ))
        
        elif self.entity_type in [EntityType.PARTNERSHIP, EntityType.MMLLC]:
            # Partnerships can have guaranteed payments
            # Then remaining income allocated by ownership
            
            total_guaranteed = sum(o.guaranteed_payments for o in self.owners.values())
            remaining_income = net_income - total_guaranteed
            
            for name, owner in self.owners.items():
                # Guaranteed payment allocation
                guaranteed = owner.guaranteed_payments
                
                # Pro-rata income allocation
                income_allocation = remaining_income * owner.ownership_percent
                
                total_allocation = guaranteed + income_allocation
                
                # Update capital account
                owner.capital_account += total_allocation
                owner.capital_account -= owner.distributions_ytd
                
                # Update basis
                owner.basis += total_allocation
                owner.basis -= owner.distributions_ytd
                
                results.append(AllocationResult(
                    owner=name,
                    ownership_percent=owner.ownership_percent,
                    allocated_income=max(0, income_allocation),
                    allocated_loss=abs(min(0, income_allocation)),
                    guaranteed_payments=guaranteed,
                    net_allocation=total_allocation,
                    ending_capital=owner.capital_account,
                    ending_basis=owner.basis
                ))
        
        return results
    
    def analyze_reasonable_compensation(
        self,
        owner_name: str,
        current_salary: float
    ) -> Dict:
        """
        Analyze if S-Corp shareholder salary is "reasonable"
        
        IRS requires S-Corp shareholders who work for company
        to take reasonable W-2 salary before distributions
        """
        
        if self.entity_type != EntityType.S_CORP:
            return {"applicable": False}
        
        owner = self.owners.get(owner_name)
        if not owner:
            return {"error": "Owner not found"}
        
        # Get industry range
        comp_range = self.REASONABLE_COMP_RANGES.get(
            self.industry,
            self.REASONABLE_COMP_RANGES["default"]
        )
        
        min_reasonable, max_reasonable = comp_range
        
        # Calculate recommended salary
        # Rule of thumb: 35-50% of net business income
        target_percent = 0.40
        recommended_salary = self.ytd_income * target_percent
        recommended_salary = max(min_reasonable, min(recommended_salary, max_reasonable))
        
        # Analyze current salary
        if current_salary < min_reasonable:
            status = "TOO_LOW"
            risk = "HIGH"
            message = f"Salary ${current_salary:,.0f} below reasonable range ${min_reasonable:,.0f}-${max_reasonable:,.0f}"
        elif current_salary > max_reasonable:
            status = "TOO_HIGH"
            risk = "MEDIUM"
            message = f"Salary ${current_salary:,.0f} above typical range - consider distributions"
        else:
            status = "REASONABLE"
            risk = "LOW"
            message = f"Salary ${current_salary:,.0f} within reasonable range"
        
        # Calculate tax impact
        # Salary: subject to FICA (15.3%)
        # Distributions: no FICA
        salary_fica = current_salary * 0.153
        recommended_fica = recommended_salary * 0.153
        fica_difference = salary_fica - recommended_fica
        
        return {
            "applicable": True,
            "current_salary": current_salary,
            "reasonable_range": comp_range,
            "recommended_salary": recommended_salary,
            "status": status,
            "audit_risk": risk,
            "message": message,
            "tax_analysis": {
                "current_fica": salary_fica,
                "recommended_fica": recommended_fica,
                "potential_savings": fica_difference if fica_difference > 0 else 0,
                "note": "Lower salary saves FICA but must be 'reasonable'"
            },
            "recommendations": self._get_salary_recommendations(
                current_salary, recommended_salary, status
            )
        }
    
    def _get_salary_recommendations(
        self,
        current: float,
        recommended: float,
        status: str
    ) -> List[str]:
        """Generate salary recommendations"""
        
        recs = []
        
        if status == "TOO_LOW":
            recs.extend([
                f"Increase salary to at least ${recommended:,.0f}",
                "Document job duties and responsibilities",
                "Compare to similar positions in industry",
                "Adjust payroll before year-end to reduce audit risk"
            ])
        elif status == "TOO_HIGH":
            recs.extend([
                f"Consider reducing salary to ${recommended:,.0f}",
                "Take additional distributions (no FICA)",
                "Maximize retirement contributions instead",
                "Consult with CPA for optimal split"
            ])
        else:
            recs.extend([
                "Current salary appears reasonable",
                "Document methodology for salary determination",
                "Review annually based on business performance"
            ])
        
        return recs
    
    def prepare_k1_data(
        self,
        tax_year: int
    ) -> Dict:
        """
        Prepare Schedule K-1 data for owners
        
        K-1 reports:
        - Share of income/loss
        - Distributions
        - Capital account changes
        - Basis
        """
        
        # Calculate allocations
        net_income = self.ytd_income - self.ytd_expenses
        allocations = self.calculate_allocations(net_income)
        
        k1_data = {
            "entity_name": self.entity_name,
            "entity_type": self.entity_type.value,
            "tax_year": tax_year,
            "ein": "XX-XXXXXXX",  # Would be actual EIN
            "owner_k1s": []
        }
        
        for allocation in allocations:
            owner = self.owners[allocation.owner]
            
            k1 = {
                "owner_name": allocation.owner,
                "ownership_percent": allocation.ownership_percent,
                
                # Box 1: Ordinary business income/loss
                "ordinary_income": allocation.allocated_income,
                "ordinary_loss": allocation.allocated_loss,
                
                # Box 2: Net rental real estate income/loss
                "rental_income": 0,  # Would be calculated
                
                # Box 3: Other net rental income/loss
                "other_rental": 0,
                
                # Box 4: Guaranteed payments
                "guaranteed_payments": allocation.guaranteed_payments,
                
                # Box 5: Interest income
                "interest_income": 0,
                
                # Boxes 6-13: Various other items
                # (simplified for this example)
                
                # Box 14: Self-employment earnings
                "se_earnings": allocation.net_allocation if self.entity_type == EntityType.PARTNERSHIP else 0,
                
                # Box 19: Distributions
                "distributions": owner.distributions_ytd,
                
                # Capital account analysis
                "capital_account": {
                    "beginning": owner.initial_capital,
                    "capital_contributed": 0,  # Would track
                    "current_year_income": allocation.net_allocation,
                    "withdrawals_distributions": owner.distributions_ytd,
                    "ending": allocation.ending_capital
                },
                
                # Partner's basis
                "partner_basis": {
                    "beginning": owner.initial_capital,
                    "increases": allocation.net_allocation if allocation.net_allocation > 0 else 0,
                    "decreases": (
                        abs(allocation.net_allocation) if allocation.net_allocation < 0 else 0
                    ) + owner.distributions_ytd,
                    "ending": allocation.ending_basis
                }
            }
            
            k1_data["owner_k1s"].append(k1)
        
        return k1_data
    
    def optimize_distribution_vs_salary(
        self,
        owner_name: str,
        total_compensation_target: float
    ) -> Dict:
        """
        Optimize mix of salary vs distributions for S-Corp owner
        
        Goal: Minimize total tax while maintaining reasonable comp
        """
        
        if self.entity_type != EntityType.S_CORP:
            return {"error": "Only applicable to S-Corps"}
        
        owner = self.owners.get(owner_name)
        if not owner:
            return {"error": "Owner not found"}
        
        # Get reasonable compensation range
        comp_analysis = self.analyze_reasonable_compensation(owner_name, 0)
        min_salary = comp_analysis["reasonable_range"][0]
        
        # Calculate optimal split
        # Strategy: Minimum reasonable salary, rest as distributions
        optimal_salary = min(min_salary, total_compensation_target)
        optimal_distribution = max(0, total_compensation_target - optimal_salary)
        
        # Calculate tax savings
        # Salary: Income tax + FICA (15.3%)
        # Distributions: Income tax only
        fica_on_salary = optimal_salary * 0.153
        fica_on_distribution = 0  # No FICA on distributions
        
        fica_saved = (total_compensation_target * 0.153) - fica_on_salary
        
        return {
            "total_target": total_compensation_target,
            "optimal_salary": optimal_salary,
            "optimal_distribution": optimal_distribution,
            "fica_on_salary": fica_on_salary,
            "fica_saved": fica_saved,
            "strategy": f"Pay ${optimal_salary:,.0f} salary (reasonable comp minimum) + ${optimal_distribution:,.0f} distribution",
            "tax_savings": fica_saved,
            "audit_risk": "LOW" if optimal_salary >= min_salary else "HIGH",
            "notes": [
                "Distributions avoid FICA tax (15.3% savings)",
                "Salary must be 'reasonable' per IRS",
                "Both salary and distributions taxed as income",
                "Consider quarterly estimated taxes on distributions"
            ]
        }