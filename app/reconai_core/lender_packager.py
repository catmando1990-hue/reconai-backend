import pandas as pd
import json
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
import os


class LenderType(Enum):
    """Supported lender types"""
    SBA_7A = "sba_7a"
    SBA_EXPRESS = "sba_express"
    STREETSHARES = "streetshares"
    FEDEX_GRANT = "fedex_grant"
    KABBAGE = "kabbage"
    ONDECK = "ondeck"
    BLUEVINE = "bluevine"
    CUSTOM = "custom"


@dataclass
class DocumentRequirement:
    """Required document for lender package"""
    name: str
    required: bool
    format: str  # "pdf", "xlsx", "docx", "json"
    description: str
    template_available: bool = False
    auto_generate: bool = False


@dataclass
class LenderProfile:
    """Complete lender requirements profile"""
    lender_name: str
    lender_type: LenderType
    documents_required: List[DocumentRequirement]
    financial_period: str  # "3_years", "2_years", "1_year"
    max_loan_amount: Optional[float] = None
    min_credit_score: Optional[int] = None
    special_requirements: List[str] = field(default_factory=list)
    underwriter_questions: List[str] = field(default_factory=list)
    submission_format: str = "digital"  # "digital" or "physical"


@dataclass
class PackageValidation:
    """Validation result for lender package"""
    is_complete: bool
    missing_items: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    ready_to_submit: bool = False
    completeness_score: float = 0.0


class LenderPackager:
    """
    Lender-specific financial package generator
    
    Creates customized documentation packages based on
    specific lender requirements
    """
    
    # Pre-defined lender profiles
    LENDER_PROFILES = {
        LenderType.SBA_7A: LenderProfile(
            lender_name="SBA 7(a) Standard",
            lender_type=LenderType.SBA_7A,
            financial_period="3_years",
            max_loan_amount=5_000_000,
            min_credit_score=680,
            documents_required=[
                DocumentRequirement(
                    name="SBA Form 1919 (Borrower Information)",
                    required=True,
                    format="pdf",
                    description="Personal background information",
                    template_available=True
                ),
                DocumentRequirement(
                    name="Personal Financial Statement",
                    required=True,
                    format="pdf",
                    description="SBA Form 413 - Personal Financial Statement",
                    template_available=True,
                    auto_generate=True
                ),
                DocumentRequirement(
                    name="Business Financial Statements (3 years)",
                    required=True,
                    format="xlsx",
                    description="Balance sheet and P&L for last 3 years",
                    auto_generate=True
                ),
                DocumentRequirement(
                    name="Business Debt Schedule",
                    required=True,
                    format="xlsx",
                    description="All current business debts with terms",
                    auto_generate=True
                ),
                DocumentRequirement(
                    name="Profit & Loss Statement (YTD)",
                    required=True,
                    format="xlsx",
                    description="Year-to-date P&L",
                    auto_generate=True
                ),
                DocumentRequirement(
                    name="Business Tax Returns (3 years)",
                    required=True,
                    format="pdf",
                    description="Complete business tax returns",
                    template_available=False
                ),
                DocumentRequirement(
                    name="Personal Tax Returns (3 years)",
                    required=True,
                    format="pdf",
                    description="Personal 1040s for all owners 20%+",
                    template_available=False
                ),
                DocumentRequirement(
                    name="Expense Categorization Report",
                    required=True,
                    format="xlsx",
                    description="Detailed expense breakdown with categories",
                    auto_generate=True
                ),
                DocumentRequirement(
                    name="Business Plan",
                    required=True,
                    format="docx",
                    description="Executive summary and use of proceeds",
                    template_available=True
                ),
                DocumentRequirement(
                    name="Accounts Receivable Aging",
                    required=False,
                    format="xlsx",
                    description="AR aging if applicable",
                    auto_generate=False
                )
            ],
            special_requirements=[
                "All owners with 20%+ ownership must provide personal guarantee",
                "Collateral required for loans over $25,000",
                "Business must be operating for 2+ years",
                "Must demonstrate ability to repay",
                "No businesses engaged in illegal activities"
            ],
            underwriter_questions=[
                "What is the purpose of the loan?",
                "How will loan proceeds be used?",
                "What is the source of equity injection (if required)?",
                "Do you have any pending lawsuits?",
                "Have you ever declared bankruptcy?",
                "Are you current on all federal obligations?",
                "Do you have any tax liens?",
                "What is your business continuation plan?"
            ]
        ),
        
        LenderType.SBA_EXPRESS: LenderProfile(
            lender_name="SBA Express",
            lender_type=LenderType.SBA_EXPRESS,
            financial_period="2_years",
            max_loan_amount=500_000,
            min_credit_score=700,
            documents_required=[
                DocumentRequirement(
                    name="Business Financial Statements (2 years)",
                    required=True,
                    format="xlsx",
                    description="Last 2 years financials",
                    auto_generate=True
                ),
                DocumentRequirement(
                    name="Personal Financial Statement",
                    required=True,
                    format="pdf",
                    description="SBA Form 413",
                    template_available=True,
                    auto_generate=True
                ),
                DocumentRequirement(
                    name="Business Tax Returns (2 years)",
                    required=True,
                    format="pdf",
                    description="Last 2 years business returns",
                    template_available=False
                ),
                DocumentRequirement(
                    name="YTD Profit & Loss",
                    required=True,
                    format="xlsx",
                    description="Current year P&L",
                    auto_generate=True
                )
            ],
            special_requirements=[
                "Faster processing (36 hours)",
                "Lower documentation requirements",
                "Credit score 700+ recommended",
                "Business must be operating for 1+ years"
            ],
            underwriter_questions=[
                "Purpose of loan?",
                "Use of proceeds?",
                "Personal credit score?",
                "Current debt service coverage ratio?"
            ]
        ),
        
        LenderType.STREETSHARES: LenderProfile(
            lender_name="StreetShares (Veteran Lender)",
            lender_type=LenderType.STREETSHARES,
            financial_period="1_year",
            max_loan_amount=250_000,
            min_credit_score=600,
            documents_required=[
                DocumentRequirement(
                    name="DD-214 or Veteran Status Verification",
                    required=True,
                    format="pdf",
                    description="Proof of veteran status",
                    template_available=False
                ),
                DocumentRequirement(
                    name="Business Bank Statements (6 months)",
                    required=True,
                    format="pdf",
                    description="Last 6 months business banking",
                    template_available=False
                ),
                DocumentRequirement(
                    name="Business Financial Summary",
                    required=True,
                    format="xlsx",
                    description="Revenue and expense summary",
                    auto_generate=True
                ),
                DocumentRequirement(
                    name="Business Tax Return (1 year)",
                    required=True,
                    format="pdf",
                    description="Most recent business return",
                    template_available=False
                )
            ],
            special_requirements=[
                "Veteran-owned business required",
                "Operating for 1+ years",
                "Minimum $50K annual revenue",
                "No bankruptcies in last 2 years"
            ],
            underwriter_questions=[
                "Confirm veteran ownership %",
                "Business revenue last 12 months?",
                "Monthly gross revenue?",
                "Purpose of funding?"
            ]
        ),
        
        LenderType.FEDEX_GRANT: LenderProfile(
            lender_name="FedEx Small Business Grant",
            lender_type=LenderType.FEDEX_GRANT,
            financial_period="1_year",
            max_loan_amount=50_000,
            special_requirements=[
                "Must be small business (25 or fewer employees)",
                "Operating for 6+ months",
                "Clear growth plan required",
                "Community impact story"
            ],
            documents_required=[
                DocumentRequirement(
                    name="Business Overview & Story",
                    required=True,
                    format="docx",
                    description="Company background and mission",
                    template_available=True
                ),
                DocumentRequirement(
                    name="Grant Proposal",
                    required=True,
                    format="docx",
                    description="How grant will be used",
                    template_available=True
                ),
                DocumentRequirement(
                    name="Financial Summary",
                    required=True,
                    format="xlsx",
                    description="Revenue and expenses",
                    auto_generate=True
                ),
                DocumentRequirement(
                    name="Growth Plan",
                    required=True,
                    format="docx",
                    description="3-year growth projections",
                    template_available=True
                )
            ],
            underwriter_questions=[
                "How will this grant transform your business?",
                "What community impact will you create?",
                "What is your growth vision?",
                "How does your business stand out?"
            ]
        )
    }
    
    def __init__(self, lender: str):
        """
        Initialize packager for specific lender
        
        Args:
            lender: LenderType enum value or string key
        """
        if isinstance(lender, str):
            lender = LenderType(lender.lower())
        
        if lender not in self.LENDER_PROFILES:
            raise ValueError(f"Unknown lender: {lender}")
        
        self.profile = self.LENDER_PROFILES[lender]
        self.lender_type = lender
    
    def create_package(
        self, 
        financial_data: Dict[str, Any],
        output_dir: str = "./lender_package"
    ) -> Dict:
        """
        Create complete lender package
        
        Args:
            financial_data: Dictionary with:
                - expenses_df: DataFrame of expenses
                - revenue_df: DataFrame of revenue
                - business_info: Business details
                - owner_info: Owner details
            output_dir: Where to save package files
        
        Returns:
            Package dictionary with generated documents
        """
        
        os.makedirs(output_dir, exist_ok=True)
        
        package = {
            "lender": self.profile.lender_name,
            "created_date": datetime.now().isoformat(),
            "documents": {},
            "status": "draft"
        }
        
        # Generate each required document
        for doc_req in self.profile.documents_required:
            if doc_req.auto_generate:
                doc_data = self._generate_document(doc_req, financial_data)
                package["documents"][doc_req.name] = doc_data
        
        # Generate underwriter response sheet
        package["underwriter_responses"] = self._generate_underwriter_responses(
            financial_data
        )
        
        # Create package manifest
        package["manifest"] = self._create_manifest(package)
        
        return package
    
    def _generate_document(
        self, 
        doc_req: DocumentRequirement, 
        financial_data: Dict
    ) -> Dict:
        """Generate specific document based on requirements"""
        
        if "Financial Statements" in doc_req.name:
            return self._generate_financial_statements(financial_data)
        
        elif "Profit & Loss" in doc_req.name:
            return self._generate_profit_loss(financial_data)
        
        elif "Debt Schedule" in doc_req.name:
            return self._generate_debt_schedule(financial_data)
        
        elif "Personal Financial Statement" in doc_req.name:
            return self._generate_personal_financial(financial_data)
        
        elif "Expense Categorization" in doc_req.name:
            return self._generate_expense_categorization(financial_data)
        
        elif "Financial Summary" in doc_req.name:
            return self._generate_financial_summary(financial_data)
        
        else:
            return {"status": "template_needed", "document": doc_req.name}
    
    def _generate_financial_statements(self, data: Dict) -> Dict:
        """Generate formatted financial statements"""
        
        expenses_df = data.get('expenses_df', pd.DataFrame())
        revenue_df = data.get('revenue_df', pd.DataFrame())
        
        # Group by period
        period = self.profile.financial_period
        
        # Calculate key metrics
        total_revenue = revenue_df['amount'].sum() if len(revenue_df) > 0 else 0
        total_expenses = expenses_df['amount'].sum()
        net_income = total_revenue - total_expenses
        
        # By category
        expense_by_category = expenses_df.groupby('category')['amount'].sum()
        
        return {
            "type": "financial_statements",
            "period": period,
            "summary": {
                "total_revenue": total_revenue,
                "total_expenses": total_expenses,
                "net_income": net_income,
                "profit_margin": net_income / total_revenue if total_revenue > 0 else 0
            },
            "expenses_by_category": expense_by_category.to_dict(),
            "format": "xlsx"
        }
    
    def _generate_profit_loss(self, data: Dict) -> Dict:
        """Generate P&L statement"""
        
        expenses_df = data.get('expenses_df', pd.DataFrame())
        revenue_df = data.get('revenue_df', pd.DataFrame())
        
        # Current year only
        current_year = datetime.now().year
        
        ytd_revenue = revenue_df[
            pd.to_datetime(revenue_df['date']).dt.year == current_year
        ]['amount'].sum() if len(revenue_df) > 0 else 0
        
        ytd_expenses = expenses_df[
            pd.to_datetime(expenses_df['date']).dt.year == current_year
        ]['amount'].sum()
        
        return {
            "type": "profit_loss",
            "period": "YTD",
            "revenue": ytd_revenue,
            "expenses": ytd_expenses,
            "net_income": ytd_revenue - ytd_expenses,
            "format": "xlsx"
        }
    
    def _generate_debt_schedule(self, data: Dict) -> Dict:
        """Generate business debt schedule"""
        
        debts = data.get('debts', [])
        
        total_debt = sum(d.get('balance', 0) for d in debts)
        monthly_payment = sum(d.get('monthly_payment', 0) for d in debts)
        
        return {
            "type": "debt_schedule",
            "total_debt": total_debt,
            "monthly_payment": monthly_payment,
            "debts": debts,
            "format": "xlsx"
        }
    
    def _generate_personal_financial(self, data: Dict) -> Dict:
        """Generate SBA Form 413 equivalent"""
        
        owner_info = data.get('owner_info', {})
        
        return {
            "type": "personal_financial_statement",
            "owner": owner_info.get('name', ''),
            "assets": owner_info.get('assets', {}),
            "liabilities": owner_info.get('liabilities', {}),
            "net_worth": owner_info.get('net_worth', 0),
            "format": "pdf"
        }
    
    def _generate_expense_categorization(self, data: Dict) -> Dict:
        """Generate detailed expense report"""
        
        expenses_df = data.get('expenses_df', pd.DataFrame())
        
        categorization = expenses_df.groupby(['category', 'confidence']).agg({
            'amount': ['sum', 'count', 'mean']
        }).round(2)
        
        return {
            "type": "expense_categorization",
            "total_expenses": expenses_df['amount'].sum(),
            "categories": categorization.to_dict(),
            "high_confidence_percent": len(
                expenses_df[expenses_df['confidence'] == 'HIGH']
            ) / len(expenses_df) if len(expenses_df) > 0 else 0,
            "format": "xlsx"
        }
    
    def _generate_financial_summary(self, data: Dict) -> Dict:
        """Generate one-page financial summary"""
        
        expenses_df = data.get('expenses_df', pd.DataFrame())
        revenue_df = data.get('revenue_df', pd.DataFrame())
        business_info = data.get('business_info', {})
        
        return {
            "type": "financial_summary",
            "business_name": business_info.get('name', ''),
            "revenue_ttm": revenue_df['amount'].sum() if len(revenue_df) > 0 else 0,
            "expenses_ttm": expenses_df['amount'].sum(),
            "operating_margin": "calculated",
            "format": "xlsx"
        }
    
    def _generate_underwriter_responses(self, data: Dict) -> Dict:
        """Pre-answer common underwriter questions"""
        
        responses = {}
        business_info = data.get('business_info', {})
        
        for question in self.profile.underwriter_questions:
            # Smart response generation based on question
            if "purpose" in question.lower():
                responses[question] = business_info.get(
                    'loan_purpose', 
                    'Working capital and business expansion'
                )
            
            elif "veteran" in question.lower():
                responses[question] = business_info.get(
                    'veteran_ownership_percent',
                    '100% veteran-owned'
                )
            
            elif "revenue" in question.lower():
                revenue = data.get('revenue_df', pd.DataFrame())['amount'].sum()
                responses[question] = f"${revenue:,.2f}"
            
            else:
                responses[question] = "[MANUAL INPUT REQUIRED]"
        
        return responses
    
    def _create_manifest(self, package: Dict) -> Dict:
        """Create package manifest/checklist"""
        
        manifest = {
            "lender": self.profile.lender_name,
            "created": package["created_date"],
            "required_documents": [],
            "optional_documents": [],
            "auto_generated": [],
            "manual_needed": []
        }
        
        for doc_req in self.profile.documents_required:
            doc_info = {
                "name": doc_req.name,
                "format": doc_req.format,
                "description": doc_req.description
            }
            
            if doc_req.required:
                manifest["required_documents"].append(doc_info)
            else:
                manifest["optional_documents"].append(doc_info)
            
            if doc_req.auto_generate:
                manifest["auto_generated"].append(doc_req.name)
            else:
                manifest["manual_needed"].append(doc_req.name)
        
        return manifest
    
    def validate_package(self, package: Dict) -> PackageValidation:
        """Validate package completeness"""
        
        missing = []
        warnings = []
        
        # Check required documents
        for doc_req in self.profile.documents_required:
            if doc_req.required:
                if doc_req.name not in package.get("documents", {}):
                    missing.append(doc_req.name)
        
        # Check underwriter responses
        for question in self.profile.underwriter_questions:
            response = package.get("underwriter_responses", {}).get(question, "")
            if "[MANUAL INPUT REQUIRED]" in response or not response:
                warnings.append(f"Underwriter question needs answer: {question}")
        
        completeness = 1.0 - (len(missing) / len([
            d for d in self.profile.documents_required if d.required
        ]))
        
        return PackageValidation(
            is_complete=len(missing) == 0,
            missing_items=missing,
            warnings=warnings,
            ready_to_submit=len(missing) == 0 and len(warnings) == 0,
            completeness_score=completeness
        )
    
    def export_package(
        self, 
        package: Dict, 
        output_dir: str = "./lender_package"
    ):
        """Export package to files"""
        
        os.makedirs(output_dir, exist_ok=True)
        
        # Save manifest
        with open(f"{output_dir}/PACKAGE_MANIFEST.json", 'w') as f:
            json.dump(package["manifest"], f, indent=2)
        
        # Save underwriter responses
        with open(f"{output_dir}/UNDERWRITER_RESPONSES.txt", 'w') as f:
            f.write(f"UNDERWRITER QUESTIONS - {self.profile.lender_name}\n")
            f.write("="*80 + "\n\n")
            for q, a in package.get("underwriter_responses", {}).items():
                f.write(f"Q: {q}\n")
                f.write(f"A: {a}\n\n")
        
        # Save document data
        for doc_name, doc_data in package.get("documents", {}).items():
            filename = doc_name.replace(" ", "_").replace("/", "_")
            
            if doc_data.get("format") == "xlsx":
                # Save as Excel (simplified - use openpyxl for real implementation)
                with open(f"{output_dir}/{filename}.json", 'w') as f:
                    json.dump(doc_data, f, indent=2)
            else:
                with open(f"{output_dir}/{filename}.json", 'w') as f:
                    json.dump(doc_data, f, indent=2)
        
        print(f"Package exported to {output_dir}")
        print(f"   Lender: {self.profile.lender_name}")
        print(f"   Documents: {len(package.get('documents', {}))}")