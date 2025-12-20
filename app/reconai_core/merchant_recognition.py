import re
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
import joblib
from fuzzywuzzy import fuzz
import json

from app.reconai_core.bank_intelligence import detect_bank, BANK_PROFILES

@dataclass
class MerchantInfo:
    """Standardized merchant information"""
    clean_name: str          # "Amazon Web Services"
    category: str            # "Cloud Services"
    merchant_type: str       # "Technology"
    confidence: float        # 0.0 to 1.0
    raw_description: str     # Original bank description
    reasoning: str           # Why this classification was made


class MerchantRecognizer:
    """
    AI-powered merchant recognition engine
    
    Uses combination of:
    - Pattern matching (regex rules for known formats)
    - Bank detection (100+ banks recognized)
    - Fuzzy matching (Levenshtein distance)
    - Machine learning (TF-IDF + Random Forest)
    - Business rules (domain knowledge)
    """
    
    def __init__(self, model_path: str = "models/merchant_model.pkl"):
        self.model_path = model_path
        self.vectorizer = None
        self.classifier = None
        self.merchant_patterns = self._load_patterns()
        self.known_merchants = self._load_merchant_database()
        self._load_bank_patterns()
        
    def _load_patterns(self) -> Dict[str, Dict]:
        """Load regex patterns for common merchant formats"""
        return {
            "amazon": {
                "pattern": r"AMZ[N*]?\*?[A-Z0-9]+",
                "categories": {
                    "AWS": "Cloud Services",
                    "PRIME": "Subscription",
                    "MARKETPLACE": "Retail"
                },
                "clean_name": "Amazon"
            },
            "square": {
                "pattern": r"SQ\s*\*",
                "clean_name": "Square",
                "category": "Payment Processing"
            },
            "uber": {
                "pattern": r"UBER|TST\*\s*UBER",
                "clean_name": "Uber",
                "category": "Transportation"
            },
            "lyft": {
                "pattern": r"LYFT|TST\*\s*LYFT",
                "clean_name": "Lyft", 
                "category": "Transportation"
            },
            "stripe": {
                "pattern": r"STRIPE",
                "clean_name": "Stripe",
                "category": "Payment Processing"
            },
            "google": {
                "pattern": r"GOOGLE\*|GOOGLEPAY",
                "categories": {
                    "CLOUD": "Cloud Services",
                    "WORKSPACE": "Software",
                    "ADS": "Advertising"
                },
                "clean_name": "Google"
            },
            "microsoft": {
                "pattern": r"MSFT\*|MICROSOFT",
                "categories": {
                    "AZURE": "Cloud Services",
                    "365": "Software",
                    "OFFICE": "Software"
                },
                "clean_name": "Microsoft"
            },
            "delta": {
                "pattern": r"DELTA\s*(AIR|AIRLINES?)",
                "clean_name": "Delta Airlines",
                "category": "Travel - Air"
            },
            "united": {
                "pattern": r"UNITED\s*(AIR|AIRLINES?)",
                "clean_name": "United Airlines",
                "category": "Travel - Air"
            },
            "marriott": {
                "pattern": r"MARRIOTT|COURTYARD|RESIDENCE\s*INN",
                "clean_name": "Marriott",
                "category": "Travel - Lodging"
            },
            "hilton": {
                "pattern": r"HILTON|HAMPTON\s*INN|EMBASSY\s*SUITES",
                "clean_name": "Hilton",
                "category": "Travel - Lodging"
            }
        }
    
    def _load_merchant_database(self) -> Dict[str, MerchantInfo]:
        """
        Load database of known merchants
        In production, this would be a real database with 1M+ entries
        """
        return {
            "amazon web services": MerchantInfo(
                clean_name="Amazon Web Services",
                category="Cloud Services",
                merchant_type="Technology",
                confidence=1.0,
                raw_description="",
                reasoning="Known merchant in database"
            ),
            "aws": MerchantInfo(
                clean_name="Amazon Web Services", 
                category="Cloud Services",
                merchant_type="Technology",
                confidence=1.0,
                raw_description="",
                reasoning="Known abbreviation"
            ),
            "stripe": MerchantInfo(
                clean_name="Stripe",
                category="Payment Processing",
                merchant_type="Technology",
                confidence=1.0,
                raw_description="",
                reasoning="Known merchant"
            ),
            # Add more known merchants here
        }
    
    def _clean_description(self, description: str) -> str:
        """Clean and normalize merchant description"""
        # Remove common noise
        cleaned = description.upper()
        cleaned = re.sub(r'\d{2}/\d{2}', '', cleaned)  # Remove dates
        cleaned = re.sub(r'#\d+', '', cleaned)  # Remove store numbers
        cleaned = re.sub(r'\*+', ' ', cleaned)  # Replace asterisks with spaces
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()  # Normalize whitespace
        return cleaned
    
    def _pattern_match(self, description: str) -> Optional[MerchantInfo]:
        """Try to match against known patterns"""
        cleaned = self._clean_description(description)
        
        for merchant_key, pattern_info in self.merchant_patterns.items():
            if re.search(pattern_info["pattern"], description, re.IGNORECASE):
                # Check for sub-categories
                category = pattern_info.get("category", "General")
                if "categories" in pattern_info:
                    for keyword, cat in pattern_info["categories"].items():
                        if keyword in cleaned:
                            category = cat
                            break
                
                return MerchantInfo(
                    clean_name=pattern_info["clean_name"],
                    category=category,
                    merchant_type="Detected via pattern",
                    confidence=0.95,
                    raw_description=description,
                    reasoning=f"Matched pattern: {pattern_info['pattern']}"
                )
        
        return None
    
    def _fuzzy_match(self, description: str, threshold: int = 85) -> Optional[MerchantInfo]:
        """Try fuzzy matching against known merchants"""
        cleaned = self._clean_description(description)
        
        best_match = None
        best_score = 0
        
        for known_name, merchant_info in self.known_merchants.items():
            # Use token sort ratio for better matching
            score = fuzz.token_sort_ratio(cleaned, known_name.upper())
            
            if score > best_score and score >= threshold:
                best_score = score
                best_match = merchant_info
        
        if best_match:
            return MerchantInfo(
                clean_name=best_match.clean_name,
                category=best_match.category,
                merchant_type=best_match.merchant_type,
                confidence=best_score / 100.0,
                raw_description=description,
                reasoning=f"Fuzzy match (score: {best_score}/100)"
            )
        
        return None
    
    def _ml_predict(self, description: str) -> Optional[MerchantInfo]:
        """Use ML model to predict merchant"""
        if not self.classifier or not self.vectorizer:
            return None
        
        try:
            # Transform description
            features = self.vectorizer.transform([description])
            
            # Get prediction and probability
            prediction = self.classifier.predict(features)[0]
            probabilities = self.classifier.predict_proba(features)[0]
            confidence = max(probabilities)
            
            # Parse prediction (format: "MerchantName|Category")
            if "|" in prediction:
                merchant_name, category = prediction.split("|", 1)
            else:
                merchant_name = prediction
                category = "Uncategorized"
            
            return MerchantInfo(
                clean_name=merchant_name,
                category=category,
                merchant_type="ML Prediction",
                confidence=confidence,
                raw_description=description,
                reasoning=f"ML model prediction (confidence: {confidence:.2%})"
            )
        except Exception as e:
            print(f"ML prediction error: {e}")
            return None
    
    def recognize(self, description: str) -> MerchantInfo:
        """
        Main recognition function - tries multiple methods in order
        
        Priority:
        1. Pattern matching (highest confidence)
        2. Fuzzy matching (medium confidence)
        3. ML prediction (variable confidence)
        4. Fallback (low confidence)
        """
        
        # Try pattern matching first
        result = self._pattern_match(description)
        if result and result.confidence >= 0.90:
            return result
        
        # Try fuzzy matching
        fuzzy_result = self._fuzzy_match(description)
        if fuzzy_result and fuzzy_result.confidence >= 0.85:
            return fuzzy_result
        
        # Try ML prediction
        ml_result = self._ml_predict(description)
        if ml_result and ml_result.confidence >= 0.70:
            return ml_result
        
        # Return best result or fallback
        best = max(
            [r for r in [result, fuzzy_result, ml_result] if r],
            key=lambda x: x.confidence,
            default=None
        )
        
        if best:
            return best
        
        # Fallback - extract likely merchant name
        cleaned = self._clean_description(description)
        # Take first meaningful word
        words = [w for w in cleaned.split() if len(w) > 2]
        merchant_name = words[0] if words else "Unknown Merchant"
        
        return MerchantInfo(
            clean_name=merchant_name.title(),
            category="Uncategorized",
            merchant_type="Fallback",
            confidence=0.30,
            raw_description=description,
            reasoning="No pattern match - extracted from description"
        )
    
    def train(self, training_data: pd.DataFrame):
        """
        Train the ML model on transaction data
        
        Expected columns in training_data:
        - description: Raw merchant description
        - merchant: Clean merchant name
        - category: Expense category
        """
        print("Training merchant recognition model...")
        
        # Prepare training data
        X = training_data['description'].values
        y = training_data.apply(
            lambda row: f"{row['merchant']}|{row['category']}", 
            axis=1
        ).values
        
        # Split data
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42
        )
        
        # Create TF-IDF vectorizer
        self.vectorizer = TfidfVectorizer(
            max_features=5000,
            ngram_range=(1, 3),
            lowercase=True,
            analyzer='char_wb'  # Character n-grams work well for merchant names
        )
        
        # Fit vectorizer and transform training data
        X_train_vec = self.vectorizer.fit_transform(X_train)
        X_test_vec = self.vectorizer.transform(X_test)
        
        # Train Random Forest classifier
        self.classifier = RandomForestClassifier(
            n_estimators=100,
            max_depth=20,
            min_samples_split=5,
            random_state=42,
            n_jobs=-1
        )
        
        self.classifier.fit(X_train_vec, y_train)
        
        # Evaluate
        train_score = self.classifier.score(X_train_vec, y_train)
        test_score = self.classifier.score(X_test_vec, y_test)
        
        print(f"Training accuracy: {train_score:.2%}")
        print(f"Testing accuracy: {test_score:.2%}")
        
        # Save model
        self.save_model()
        
        return {
            "train_accuracy": train_score,
            "test_accuracy": test_score,
            "n_samples": len(X_train)
        }
    
    def save_model(self, path: Optional[str] = None):
        """Save trained model to disk"""
        path = path or self.model_path
        model_data = {
            'vectorizer': self.vectorizer,
            'classifier': self.classifier
        }
        joblib.dump(model_data, path)
        print(f"Model saved to {path}")
    
    def load_model(self, path: Optional[str] = None):
        """Load trained model from disk"""
        path = path or self.model_path
        try:
            model_data = joblib.load(path)
            self.vectorizer = model_data['vectorizer']
            self.classifier = model_data['classifier']
            print(f"Model loaded from {path}")
            return True
        except FileNotFoundError:
            print(f"No model found at {path}")
            return False


# ============================================================================
# TRAINING DATA GENERATOR
# ============================================================================

def generate_sample_training_data() -> pd.DataFrame:
    """
    Generate sample training data
    In production, you'd have real transaction data
    """
    samples = [
        # Amazon variations
        ("AMZN*2K3FH7 Seattle WA", "Amazon Web Services", "Cloud Services"),
        ("AMAZON.COM*2L4M9P", "Amazon", "Retail"),
        ("AMZN MKTP US*2F4H8K", "Amazon Marketplace", "Retail"),
        ("AWS*Amazon Web Ser", "Amazon Web Services", "Cloud Services"),
        
        # Square variations
        ("SQ *COFFEE SHOP", "Coffee Shop", "Meals"),
        ("SQ *BARBER SHOP", "Barber Shop", "Personal Care"),
        ("SQUARE *RETAIL", "Retail Store", "Supplies"),
        
        # Travel
        ("DELTA AIR 00623451234", "Delta Airlines", "Travel - Air"),
        ("UNITED 0162345123456", "United Airlines", "Travel - Air"),
        ("MARRIOTT HOTEL #234", "Marriott", "Travel - Lodging"),
        ("HILTON ATLANTA", "Hilton", "Travel - Lodging"),
        
        # Uber/Lyft
        ("UBER *TRIP", "Uber", "Transportation"),
        ("TST* UBER TRIP", "Uber", "Transportation"),
        ("LYFT *RIDE", "Lyft", "Transportation"),
        
        # Gas stations
        ("SHELL OIL #12345", "Shell", "Fuel"),
        ("EXXONMOBIL 67890", "ExxonMobil", "Fuel"),
        ("CHEVRON #55555", "Chevron", "Fuel"),
        
        # Restaurants
        ("CHIPOTLE #1234", "Chipotle", "Meals"),
        ("STARBUCKS STORE 5678", "Starbucks", "Meals"),
        ("MCDONALD'S #9012", "McDonald's", "Meals"),
        
        # Cloud/SaaS
        ("GOOGLE*CLOUD", "Google Cloud", "Cloud Services"),
        ("MSFT*AZURE", "Microsoft Azure", "Cloud Services"),
        ("DIGITALOCEAN.COM", "DigitalOcean", "Cloud Services"),
        ("HEROKU 234-567-890", "Heroku", "Cloud Services"),
        
        # Payment processors
        ("STRIPE", "Stripe", "Payment Processing"),
        ("PAYPAL *TRANSFER", "PayPal", "Payment Processing"),
        ("BRAINTREE", "Braintree", "Payment Processing"),
    ]
    
    # Create DataFrame
    df = pd.DataFrame(samples, columns=['description', 'merchant', 'category'])
    
    # Augment with variations (simulate real-world noise)
    augmented = []
    for _, row in df.iterrows():
        # Original
        augmented.append(row.to_dict())
        
        # Add location codes
        augmented.append({
            'description': f"{row['description']} CA",
            'merchant': row['merchant'],
            'category': row['category']
        })
        
        # Add extra spaces
        augmented.append({
            'description': row['description'].replace('*', ' * '),
            'merchant': row['merchant'],
            'category': row['category']
        })
    
    return pd.DataFrame(augmented)