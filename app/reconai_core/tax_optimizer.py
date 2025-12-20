import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import json
import re


class ServiceBranch(Enum):
    """Military service branches"""
    ARMY = "army"
    NAVY = "navy"
    AIR_FORCE = "air_force"
    MARINES = "marines"
    COAST_GUARD = "coast_guard"
    SPACE_FORCE = "space_force"


class DischargeType(Enum):
    """Discharge characterizations"""
    HONORABLE = "honorable"
    GENERAL = "general"
    OTHER_THAN_HONORABLE = "other_than_honorable"
    BAD_CONDUCT = "bad_conduct"
    DISHONORABLE = "dishonorable"


@dataclass
class DD214Data:
    """DD Form 214 - Certificate of Release or Discharge"""
    service_branch: ServiceBranch
    entry_date: datetime
    separation_date: datetime
    discharge_type: DischargeType
    mos: str  # Military Occupational Specialty
    rank: str
    service_years: float
    deployments: List[str] = field(default_factory=list)
    awards: List[str] = field(default_factory=list)
    disability_rating: int = 0  # VA disability %


@dataclass
class VAIncome:
    """VA income record"""
    income_type: str  # "disability", "pension", "education", "voc_rehab"
    monthly_amount: float
    effective_date: datetime
    is_taxable: bool
    service_connected: bool


@dataclass
class GrantProgram:
    """Veteran grant program details"""
    name: str
    provider: str
    max_amount: float
    eligibility_requirements: List[str]
    application_deadline: Optional[datetime]
    required_documents: List[str]
    website: str
    veteran_only: bool


class VeteranTracker:
    """
    Veteran-specific financial intelligence system
    
    Handles:
    - VA income tracking (non-taxable)
    - Military travel reconciliation
    - Veteran certification documentation
    - Grant application automation
    - Service-connected expense tracking
    """
    
    # VA Disability Compensation Rates (2024)
    VA_DISABILITY_RATES = {
        # Disability rating percentage: monthly amount
        10: 171.23,
        20: 338.49,
        30: 524.31,
        40: 755.28,
        50: 1075.16,
        60: 1361.88,
        70: 1716.28,
        80: 1995.01,
        90: 2241.91,
        100: 3737.85
    }
    
    # Additional amounts for dependents, special monthly compensation, etc
    # (simplified - real implementation would include all VA rate tables)
    
    # Veteran grant programs
    GRANT_PROGRAMS = {
        "streetshares": GrantProgram(
            name="StreetShares Foundation",
            provider="StreetShares",
            max_amount=100000,
            eligibility_requirements=[
                "Veteran-owned business (51%+)",
                "Operating for 1+ years",
                "Minimum $50K annual revenue",
                "No bankruptcies in last 2 years",
                "Credit score 600+"
            ],
            application_deadline=None,  # Rolling
            required_documents=[
                "DD-214",
                "Business tax returns (1 year)",
                "Business bank statements (6 months)",
                "Business plan or use of proceeds"
            ],
            website="https://streetshares.com/foundation",
            veteran_only=True
        ),
        
        "fedex_veteran": GrantProgram(
            name="FedEx Small Business Grant (Veteran Track)",
            provider="FedEx",
            max_amount=50000,
            eligibility_requirements=[
                "Veteran-owned business",
                "Small business (25 or fewer employees)",
                "Operating for 6+ months",
                "Clear growth plan"
            ],
            application_deadline=None,  # Annual
            required_documents=[
                "DD-214 or veteran verification",
                "Business overview",
                "Financial summary",
                "Growth plan"
            ],
            website="https://smallbusinessgrant.fedex.com",
            veteran_only=True
        ),
        
        "vwise": GrantProgram(
            name="V-WISE (Veteran Women Igniting the Spirit of Entrepreneurship)",
            provider="Syracuse University / SBA",
            max_amount=0,  # Training program, not grant
            eligibility_requirements=[
                "Female veteran or spouse of veteran",
                "Interest in entrepreneurship",
                "Commitment to 3-phase program"
            ],
            application_deadline=None,  # Cohort-based
            required_documents=[
                "Veteran status verification",
                "Application form",
                "Business idea description"
            ],
            website="https://vwise.whitman.syr.edu",
            veteran_only=True
        ),
        
        "hivers_strivers": GrantProgram(
            name="Hivers and Strivers",
            provider="Hivers and Strivers Angel Network",
            max_amount=250000,
            eligibility_requirements=[
                "Veteran CEO or founder",
                "High-growth startup",
                "Scalable business model",
                "Post-9/11 veteran preferred"
            ],
            application_deadline=None,  # Rolling
            required_documents=[
                "DD-214",
                "Executive summary",
                "Financial projections",
                "Pitch deck"
            ],
            website="https://www.hiversandstrivers.com",
            veteran_only=True
        )
    }
    
    def __init__(
        self,
        dd214_data: Dict,
        business_name: str,
        veteran_ownership_percent: float = 1.0
    ):
        """
        Initialize veteran tracker
        
        Args:
            dd214_data: DD-214 information dictionary
            business_name: Legal business name
            veteran_ownership_percent: Veteran ownership (0.51-1.0 for VOSB)
        """
        
        self.business_name = business_name
        self.veteran_ownership = veteran_ownership_percent
        
        # Parse DD-214 data
        self.dd214 = DD214Data(
            service_branch=ServiceBranch(dd214_data.get('service_branch', 'army').lower()),
            entry_date=pd.to_datetime(dd214_data.get('entry_date', '2000-01-01')),
            separation_date=pd.to_datetime(dd214_data.get('separation_date', '2010-01-01')),
            discharge_type=DischargeType(dd214_data.get('discharge_type', 'honorable').lower()),
            mos=dd214_data.get('mos', ''),
            rank=dd214_data.get('rank', ''),
            service_years=dd214_data.get('service_years', 0),
            deployments=dd214_data.get('deployments', []),
            awards=dd214_data.get('awards', []),
            disability_rating=dd214_data.get('disability_rating', 0)
        )
        
        # VA income tracking
        self.va_income_sources: List[VAIncome] = []
        
        # Certifications
        self.certifications = {
            "vosb": veteran_ownership_percent >= 0.51,  # Veteran-Owned Small Business
            "sdvosb": False,  # Service-Disabled Veteran-Owned Small Business
            "vba_verified": False  # VA verification completed
        }
        
        # Update SDVOSB if disability rating
        if self.dd214.disability_rating > 0 and self.veteran_ownership >= 0.51:
            self.certifications["sdvosb"] = True
    
    def record_va_income(
        self,
        income_type: str,
        monthly_amount: float,
        effective_date: str,
        service_connected: bool = True
    ):
        """
        Record VA income source
        
        VA income types:
        - disability: Compensation (non-taxable)
        - pension: Needs-based pension
        - education: GI Bill® benefits (non-taxable)
        - voc_rehab: Vocational Rehabilitation
        """
        
        # Determine if taxable
        is_taxable = income_type not in ['disability', 'education']
        
        va_income = VAIncome(
            income_type=income_type,
            monthly_amount=monthly_amount,
            effective_date=pd.to_datetime(effective_date),
            is_taxable=is_taxable,
            service_connected=service_connected
        )
        
        self.va_income_sources.append(va_income)
    
    def calculate_va_disability_amount(self) -> Dict:
        """
        Calculate expected VA disability compensation
        
        Returns verification of correct payment amount
        """
        
        if self.dd214.disability_rating == 0:
            return {
                "eligible": False,
                "rating": 0,
                "expected_monthly": 0
            }
        
        # Get base rate
        base_rate = self.VA_DISABILITY_RATES.get(
            self.dd214.disability_rating,
            0
        )
        
        # Note: Real implementation would include:
        # - Dependent allowances
        # - Special Monthly Compensation (SMC)
        # - Individual Unemployability (TDIU)
        # - Aid and Attendance
        
        return {
            "eligible": True,
            "rating": self.dd214.disability_rating,
            "expected_monthly": base_rate,
            "annual_amount": base_rate * 12,
            "is_taxable": False,
            "note": "VA disability compensation is non-taxable income"
        }
    
    def verify_eligibility(
        self,
        grant_program: str
    ) -> Dict:
        """
        Verify eligibility for veteran grant program
        
        Returns:
            Eligibility status and missing requirements
        """
        
        if grant_program not in self.GRANT_PROGRAMS:
            return {"error": f"Unknown grant program: {grant_program}"}
        
        program = self.GRANT_PROGRAMS[grant_program]
        
        eligible = True
        missing_requirements = []
        met_requirements = []
        
        # Check veteran ownership
        if "Veteran-owned business (51%+)" in program.eligibility_requirements:
            if self.veteran_ownership >= 0.51:
                met_requirements.append("Veteran ownership 51%+")
            else:
                eligible = False
                missing_requirements.append(f"Need 51% veteran ownership (currently {self.veteran_ownership:.1%})")
        
        # Check discharge status
        if self.dd214.discharge_type not in [DischargeType.HONORABLE, DischargeType.GENERAL]:
            eligible = False
            missing_requirements.append("Requires honorable or general discharge")
        else:
            met_requirements.append("Eligible discharge status")
        
        # Check certifications
        if self.certifications.get("vosb"):
            met_requirements.append("VOSB certified")
        
        if self.certifications.get("sdvosb"):
            met_requirements.append("SDVOSB certified (service-disabled)")
        
        return {
            "program": program.name,
            "eligible": eligible,
            "veteran_ownership": self.veteran_ownership,
            "discharge_type": self.dd214.discharge_type.value,
            "disability_rating": self.dd214.disability_rating,
            "certifications": self.certifications,
            "met_requirements": met_requirements,
            "missing_requirements": missing_requirements,
            "required_documents": program.required_documents,
            "max_grant_amount": program.max_amount,
            "application_url": program.website
        }
    
    def prepare_grant_application(
        self,
        grant_program: str,
        business_data: Dict
    ) -> Dict:
        """
        Prepare veteran grant application package
        
        Auto-fills application with veteran-specific data
        """
        
        eligibility = self.verify_eligibility(grant_program)
        
        if not eligibility.get("eligible"):
            return {
                "status": "ineligible",
                "reason": eligibility.get("missing_requirements"),
                "program": grant_program
            }
        
        program = self.GRANT_PROGRAMS[grant_program]
        
        # Build application package
        application = {
            "program": program.name,
            "applicant_type": "veteran_owned_business",
            
            # Veteran information
            "veteran_info": {
                "service_branch": self.dd214.service_branch.value,
                "rank": self.dd214.rank,
                "mos": self.dd214.mos,
                "entry_date": self.dd214.entry_date.strftime("%Y-%m-%d"),
                "separation_date": self.dd214.separation_date.strftime("%Y-%m-%d"),
                "years_served": self.dd214.service_years,
                "discharge_type": self.dd214.discharge_type.value,
                "deployments": self.dd214.deployments,
                "awards": self.dd214.awards,
                "disability_rating": self.dd214.disability_rating
            },
            
            # Business information
            "business_info": {
                "name": self.business_name,
                "veteran_ownership_percent": self.veteran_ownership,
                "vosb_certified": self.certifications.get("vosb"),
                "sdvosb_certified": self.certifications.get("sdvosb"),
                **business_data
            },
            
            # Required documents checklist
            "required_documents": {
                doc: "pending" for doc in program.required_documents
            },
            
            # Veteran-specific narrative points
            "narrative_points": self._generate_veteran_narrative(),
            
            # Program details
            "program_details": {
                "max_grant": program.max_amount,
                "deadline": program.application_deadline.isoformat() if program.application_deadline else "Rolling",
                "website": program.website
            }
        }
        
        return application
    
    def _generate_veteran_narrative(self) -> List[str]:
        """
        Generate veteran-specific narrative points for applications
        
        Helps tell the veteran's story
        """
        
        points = []
        
        # Service background
        points.append(
            f"Served {self.dd214.service_years:.1f} years in the "
            f"{self.dd214.service_branch.value.replace('_', ' ').title()}"
        )
        
        if self.dd214.rank:
            points.append(f"Achieved rank of {self.dd214.rank}")
        
        # Deployments
        if self.dd214.deployments:
            points.append(
                f"Combat/deployment experience: {', '.join(self.dd214.deployments)}"
            )
        
        # Awards
        if self.dd214.awards:
            points.append(
                f"Military honors: {', '.join(self.dd214.awards[:3])}"
            )
        
        # Disability
        if self.dd214.disability_rating > 0:
            points.append(
                f"Service-connected disability rating: {self.dd214.disability_rating}%"
            )
        
        # Skills translation
        if self.dd214.mos:
            points.append(
                f"Military occupational specialty ({self.dd214.mos}) "
                f"translates to business through [explain relevant skills]"
            )
        
        # Leadership
        points.append(
            "Military leadership experience includes [team size, responsibilities]"
        )
        
        # Values
        points.append(
            "Veteran values of discipline, integrity, and mission focus "
            "drive business culture"
        )
        
        return points
    
    def reconcile_dts_voucher(
        self,
        voucher_data: Dict
    ) -> Dict:
        """
        Reconcile Defense Travel System (DTS) voucher
        
        Matches military travel reimbursements to expenses
        """
        
        # DTS voucher contains:
        # - Travel dates
        # - Destinations
        # - Per diem claimed
        # - Actual expenses
        # - Reimbursement amount
        
        reconciliation = {
            "voucher_number": voucher_data.get("voucher_number"),
            "travel_dates": {
                "start": voucher_data.get("start_date"),
                "end": voucher_data.get("end_date")
            },
            "reimbursed_amount": voucher_data.get("reimbursement", 0),
            "is_taxable": False,  # Military travel reimbursements non-taxable
            "matched_expenses": [],
            "unmatched_expenses": [],
            "notes": []
        }
        
        # Military travel reimbursements are non-taxable
        # Should not be included in business income
        reconciliation["notes"].append(
            "Military travel reimbursements are non-taxable and "
            "should not be reported as business income"
        )
        
        return reconciliation
    
    def generate_vosb_certification_package(self) -> Dict:
        """
        Generate Veteran-Owned Small Business certification package
        
        For VA verification database
        """
        
        package = {
            "certification_type": "VOSB/SDVOSB",
            "business_name": self.business_name,
            "veteran_ownership": self.veteran_ownership,
            
            # VOSB requirements
            "vosb_eligible": self.veteran_ownership >= 0.51,
            
            # SDVOSB requirements
            "sdvosb_eligible": (
                self.veteran_ownership >= 0.51 and 
                self.dd214.disability_rating > 0
            ),
            
            # Required documentation
            "required_documents": [
                "DD Form 214 (Certificate of Release/Discharge)",
                "Business formation documents",
                "Operating agreement showing veteran control",
                "VA letter confirming disability rating" if self.dd214.disability_rating > 0 else None,
                "Personal financial statement",
                "Resume showing veteran qualifications"
            ],
            
            # Veteran information for verification
            "veteran_info": {
                "service_branch": self.dd214.service_branch.value,
                "discharge_type": self.dd214.discharge_type.value,
                "service_years": self.dd214.service_years,
                "disability_rating": self.dd214.disability_rating
            },
            
            # Next steps
            "certification_process": [
                "Register in SAM.gov (System for Award Management)",
                "Submit documents to VA CVE (Center for Veterans Enterprise)",
                "Complete VetCert questionnaire",
                "Provide supporting documentation",
                "Undergo site visit (if required)",
                "Receive certification decision (45-90 days)"
            ],
            
            "benefits": [
                "Access to federal contracting set-asides",
                "Preference in VA contracts",
                "Eligibility for veteran-specific grants",
                "Enhanced credibility with veteran-focused lenders",
                "Networking through veteran business organizations"
            ]
        }
        
        return package