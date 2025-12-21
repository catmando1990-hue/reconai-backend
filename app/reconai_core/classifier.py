from __future__ import annotations
from typing import Optional, Dict, List, Tuple
import re
import os
import json
from datetime import datetime


# ============================================================================
# MERCHANT KEYWORD DATABASE - 200+ MERCHANTS
# ============================================================================

BUSINESS_KEYWORDS = {
    # ==================== TRAVEL ====================
    # Airlines
    'delta': 'business', 'american airlines': 'business', 'united airlines': 'business',
    'southwest': 'business', 'jetblue': 'business', 'alaska airlines': 'business',
    'spirit airlines': 'business', 'frontier airlines': 'business', 'allegiant': 'business',
    
    # Hotels & Lodging
    'marriott': 'business', 'hilton': 'business', 'hyatt': 'business', 'sheraton': 'business',
    'westin': 'business', 'holiday inn': 'business', 'hampton inn': 'business',
    'courtyard': 'business', 'residence inn': 'business', 'doubletree': 'business',
    'best western': 'business', 'la quinta': 'business', 'comfort inn': 'business',
    'super 8': 'business', 'motel 6': 'business', 'airbnb': 'business', 'vrbo': 'business',
    
    # Car Rentals
    'hertz': 'business', 'enterprise': 'business', 'avis': 'business', 'budget rent': 'business',
    'national car': 'business', 'alamo': 'business', 'thrifty': 'business', 'dollar rent': 'business',
    
    # Rideshare (Business travel)
    'uber': 'business', 'lyft': 'business',
    
    # ==================== FUEL & VEHICLE ====================
    'shell': 'business', 'chevron': 'business', 'exxon': 'business', 'mobil': 'business',
    'bp gas': 'business', 'texaco': 'business', 'arco': 'business', 'marathon': 'business',
    'valero': 'business', 'sunoco': 'business', 'speedway': 'business', 'wawa': 'business',
    '76 gas': 'business', 'circle k': 'business', 'pilot': 'business', 'loves': 'business',
    
    # ==================== CLOUD & SOFTWARE ====================
    'aws': 'business', 'amazon web services': 'business', 'azure': 'business',
    'google cloud': 'business', 'google workspace': 'business', 'digitalocean': 'business',
    'linode': 'business', 'vultr': 'business', 'heroku': 'business',
    
    'microsoft 365': 'business', 'office 365': 'business', 'adobe': 'business',
    'salesforce': 'business', 'hubspot': 'business', 'mailchimp': 'business',
    'constant contact': 'business', 'shopify': 'business', 'squarespace': 'business',
    'wix': 'business', 'wordpress': 'business', 'godaddy': 'business', 'namecheap': 'business',
    
    'slack': 'business', 'zoom': 'business', 'webex': 'business', 'teams': 'business',
    'dropbox': 'business', 'box.com': 'business', 'notion': 'business', 'asana': 'business',
    'trello': 'business', 'monday.com': 'business', 'clickup': 'business',
    
    'github': 'business', 'gitlab': 'business', 'bitbucket': 'business',
    'jira': 'business', 'confluence': 'business', 'figma': 'business', 'canva pro': 'business',
    
    # ==================== OFFICE & SUPPLIES ====================
    'staples': 'business', 'office depot': 'business', 'office max': 'business',
    'amazon business': 'business', 'uline': 'business', 'grainger': 'business',
    'quill': 'business', 'viking': 'business',
    
    # ==================== SHIPPING & LOGISTICS ====================
    'fedex': 'business', 'ups': 'business', 'usps': 'business', 'dhl': 'business',
    'ups store': 'business', 'fedex office': 'business', 'pak mail': 'business',
    'stamps.com': 'business', 'shipstation': 'business', 'pirateship': 'business',
    
    # ==================== COMMUNICATIONS ====================
    'verizon': 'business', 'at&t': 'business', 't-mobile': 'business', 'sprint': 'business',
    'comcast': 'business', 'spectrum': 'business', 'cox': 'business', 'xfinity': 'business',
    'frontier': 'business', 'centurylink': 'business', 'windstream': 'business',
    
    # ==================== INSURANCE ====================
    'geico': 'business', 'state farm': 'business', 'progressive': 'business',
    'allstate': 'business', 'farmers': 'business', 'usaa': 'business', 'liberty mutual': 'business',
    'nationwide': 'business', 'travelers': 'business', 'hartford': 'business',
    
    # ==================== FINANCIAL & ACCOUNTING ====================
    'quickbooks': 'business', 'xero': 'business', 'freshbooks': 'business',
    'wave': 'business', 'gusto': 'business', 'adp': 'business', 'paychex': 'business',
    'stripe': 'business', 'square': 'business', 'paypal business': 'business',
    
    # ==================== MARKETING & ADVERTISING ====================
    'google ads': 'business', 'facebook ads': 'business', 'meta ads': 'business',
    'linkedin ads': 'business', 'twitter ads': 'business', 'tiktok ads': 'business',
    'yelp': 'business', 'angi': 'business', 'thumbtack': 'business',
    
    # ==================== PROFESSIONAL SERVICES ====================
    'legalzoom': 'business', 'rocket lawyer': 'business', 'nolo': 'business',
    'h&r block': 'business', 'turbotax business': 'business', 'incfile': 'business',
    'zenbusiness': 'business', 'northwest registered': 'business',
}

PERSONAL_KEYWORDS = {
    # ==================== GROCERIES ====================
    'walmart': 'personal', 'target': 'personal', 'costco': 'personal', 'sam\'s club': 'personal',
    'kroger': 'personal', 'safeway': 'personal', 'albertsons': 'personal', 'publix': 'personal',
    'whole foods': 'personal', 'trader joe': 'personal', 'aldi': 'personal', 'lidl': 'personal',
    'wegmans': 'personal', 'heb': 'personal', 'winco': 'personal', 'food lion': 'personal',
    'giant eagle': 'personal', 'stop & shop': 'personal', 'harris teeter': 'personal',
    
    # ==================== RESTAURANTS & FAST FOOD ====================
    'mcdonald': 'personal', 'burger king': 'personal', 'wendy\'s': 'personal',
    'taco bell': 'personal', 'chipotle': 'personal', 'panera': 'personal',
    'subway': 'personal', 'starbucks': 'personal', 'dunkin': 'personal',
    'chick-fil-a': 'personal', 'popeyes': 'personal', 'kfc': 'personal',
    'pizza hut': 'personal', 'domino': 'personal', 'papa john': 'personal',
    'little caesars': 'personal', 'five guys': 'personal', 'shake shack': 'personal',
    'in-n-out': 'personal', 'whataburger': 'personal', 'sonic': 'personal',
    'arby\'s': 'personal', 'hardee\'s': 'personal', 'carl\'s jr': 'personal',
    
    # Food Delivery
    'uber eats': 'personal', 'doordash': 'personal', 'grubhub': 'personal',
    'postmates': 'personal', 'seamless': 'personal', 'caviar': 'personal',
    
    # ==================== RETAIL & SHOPPING ====================
    'amazon': 'personal', 'ebay': 'personal', 'etsy': 'personal',
    'best buy': 'personal', 'apple store': 'personal', 'microsoft store': 'personal',
    'gamestop': 'personal', 'barnes & noble': 'personal', 'books-a-million': 'personal',
    
    # ==================== ENTERTAINMENT ====================
    'netflix': 'personal', 'hulu': 'personal', 'disney+': 'personal', 'hbo max': 'personal',
    'prime video': 'personal', 'paramount': 'personal', 'peacock': 'personal',
    'spotify': 'personal', 'apple music': 'personal', 'youtube premium': 'personal',
    'xbox': 'personal', 'playstation': 'personal', 'nintendo': 'personal', 'steam': 'personal',
    
    # ==================== PERSONAL CARE ====================
    'cvs': 'personal', 'walgreens': 'personal', 'rite aid': 'personal',
    'sephora': 'personal', 'ulta': 'personal', 'sally beauty': 'personal',
    'great clips': 'personal', 'supercuts': 'personal', 'sport clips': 'personal',
    
    # ==================== GYM & FITNESS ====================
    'planet fitness': 'personal', '24 hour fitness': 'personal', 'la fitness': 'personal',
    'lifetime fitness': 'personal', 'equinox': 'personal', 'orangetheory': 'personal',
    'crossfit': 'personal', 'ymca': 'personal', 'peloton': 'personal',
}

TRANSFER_KEYWORDS = [
    'transfer', 'zelle', 'venmo', 'cash app', 'paypal', 'payment',
    'wire', 'ach', 'direct deposit', 'withdrawal', 'deposit',
]


# ============================================================================
# AI-POWERED CLASSIFICATION
# ============================================================================

class AIClassifier:
    """Claude AI fallback for uncertain transactions"""
    
    def __init__(self):
        self.client = None
        self.enabled = bool(os.getenv("ANTHROPIC_API_KEY"))
        if self.enabled:
            try:
                self.client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
            except Exception:
                self.enabled = False
    
    def classify(self, description: str, amount: float, date: str = None) -> Dict:
        """Use Claude AI to classify uncertain transaction"""
        if not self.enabled:
            return None
        
        try:
            prompt = f"""Classify this financial transaction as either 'business' or 'personal'.

Transaction Details:
- Description: {description}
- Amount: ${abs(amount):.2f}
- Type: {'Expense' if amount < 0 else 'Income'}

Classification Rules:
BUSINESS expenses include:
- Travel: flights, hotels, car rentals, rideshare during business trips
- Technology: cloud services, software subscriptions, domains, hosting
- Office: supplies, equipment, furniture, utilities for business location
- Professional: accounting, legal, insurance, licenses, certifications
- Communications: business phone, internet, conferencing tools
- Marketing: advertising, website, social media promotions
- Shipping: postage, courier services, freight
- Fuel: if vehicle used for business

PERSONAL expenses include:
- Groceries, restaurants, food delivery
- Personal shopping, clothing, entertainment
- Gym memberships, personal subscriptions
- Home utilities (unless home office)
- Personal insurance, healthcare
- Gifts, hobbies, recreation

TRANSFERS include:
- Bank transfers, Zelle, Venmo, PayPal
- Loan payments, credit card payments
- Account movements

Respond ONLY with valid JSON in this exact format:
{{"classification": "business|personal|transfer", "confidence": "high|medium|low", "reason": "brief explanation"}}"""

            message = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=150,
                messages=[{"role": "user", "content": prompt}]
            )
            
            # Parse Claude's response
            response_text = message.content[0].text.strip()
            
            # Remove markdown code blocks if present
            if response_text.startswith('```'):
                response_text = response_text.split('\n', 1)[1].rsplit('\n', 1)[0]
            
            result = json.loads(response_text)
            
            return {
                'classification': result['classification'],
                'confidence': result.get('confidence', 'medium'),
                'reason': f"ai:{result.get('reason', 'AI classification')}"
            }
            
        except Exception as e:
            # AI failed, return None to fall back to uncertain
            print(f"AI classification error: {e}")
            return None


# ============================================================================
# MAIN CLASSIFIER
# ============================================================================

class EnterpriseClassifier:
    """Production-grade transaction classifier"""
    
    def __init__(self):
        self.ai = AIClassifier()
        self.business_keywords = BUSINESS_KEYWORDS
        self.personal_keywords = PERSONAL_KEYWORDS
        self.transfer_keywords = TRANSFER_KEYWORDS
    
    def classify(self, description: str, amount: float = 0, date: str = None) -> Dict:
        """
        Classify a transaction with fallback logic:
        1. Deterministic keyword rules (fast, free)
        2. AI classification (accurate, costs $0.003)
        3. Mark as uncertain
        """
        desc_lower = description.lower()
        
        # =================================================================
        # STEP 1: DETERMINISTIC KEYWORD MATCHING (FREE & FAST)
        # =================================================================
        
        # Check transfers first
        for keyword in self.transfer_keywords:
            if keyword in desc_lower:
                return {
                    'classification': 'transfer',
                    'confidence': 'high',
                    'reason': f'keyword:{keyword}->transfer'
                }
        
        # Check business keywords
        for keyword, category in self.business_keywords.items():
            if keyword in desc_lower:
                return {
                    'classification': 'business',
                    'confidence': 'high',
                    'reason': f'keyword:{keyword}->business'
                }
        
        # Check personal keywords
        for keyword, category in self.personal_keywords.items():
            if keyword in desc_lower:
                return {
                    'classification': 'personal',
                    'confidence': 'high',
                    'reason': f'keyword:{keyword}->personal'
                }
        
        # =================================================================
        # STEP 2: AI CLASSIFICATION (FALLBACK FOR UNCERTAIN)
        # =================================================================
        
        ai_result = self.ai.classify(description, amount, date)
        if ai_result:
            return ai_result
        
        # =================================================================
        # STEP 3: MARK AS UNCERTAIN
        # =================================================================
        
        return {
            'classification': 'uncertain',
            'confidence': 'low',
            'reason': 'no_rule_match->uncertain'
        }


# ============================================================================
# GLOBAL INSTANCE
# ============================================================================

_classifier_instance = None

def get_classifier() -> EnterpriseClassifier:
    """Get singleton classifier instance"""
    global _classifier_instance
    if _classifier_instance is None:
        _classifier_instance = EnterpriseClassifier()
    return _classifier_instance


def classify_transaction(description: str, amount: float = 0, date: str = None) -> Dict:
    """Main entry point for transaction classification"""
    classifier = get_classifier()
    return classifier.classify(description, amount, date)


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def get_classification_stats() -> Dict:
    """Get classifier statistics"""
    classifier = get_classifier()
    return {
        'business_keywords': len(classifier.business_keywords),
        'personal_keywords': len(classifier.personal_keywords),
        'transfer_keywords': len(classifier.transfer_keywords),
        'ai_enabled': classifier.ai.enabled,
        'total_keywords': len(classifier.business_keywords) + len(classifier.personal_keywords),
    }


def add_custom_keyword(keyword: str, classification: str):
    """Add a custom keyword to the classifier"""
    classifier = get_classifier()
    keyword_lower = keyword.lower()
    
    if classification == 'business':
        classifier.business_keywords[keyword_lower] = 'business'
    elif classification == 'personal':
        classifier.personal_keywords[keyword_lower] = 'personal'
    elif classification == 'transfer':
        if keyword_lower not in classifier.transfer_keywords:
            classifier.transfer_keywords.append(keyword_lower)