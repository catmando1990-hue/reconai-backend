# app/reconai_core/classifier.py
from ..models import Transaction

def classify_transaction(tx: Transaction) -> str:
    """
    Rough, rule-based classifier.
    This is where we'll later plug in smarter logic or GPT-assisted classification.
    """
    text = f"{tx.description or ''} {tx.merchant or ''}".lower()
    
    business_keywords = [
        "llc", "corp", "stripe", "square", "quickbooks", "shopify",
        "fuel", "gas", "shell", "chevron", "exxon",
        "hotel", "motel", "airbnb", "marriott", "hilton", "hyatt",
        "uber", "lyft", "airport", "airlines", "expedia", "travelocity", "booking",
        "office", "software", "ads", "google ads", "facebook ads",
        "equipment", "tools", "hardware", "subscription", "zoom", "slack",
        "security", "training", "consulting", "invoice", "client",
        "aws", "amazon web services", "azure", "digitalocean",
        "staples", "office depot",
    ]
    
    personal_keywords = [
        "netflix", "hulu", "spotify", "disney", "prime video",
        "walmart", "target", "mcdonald", "starbucks", "chipotle",
        "xbox", "playstation", "gamestop", "movie", "theater",
        "personal", "family", "grocery", "groceries",
        "publix", "kroger", "safeway", "whole foods",
        "five guys", "burger", "wendy", "taco bell", "subway",
    ]
    
    for kw in business_keywords:
        if kw in text:
            return "business"
    
    for kw in personal_keywords:
        if kw in text:
            return "personal"
    
    # If it's clearly income (positive) and description hints at wages/invoice
    if tx.amount > 0:
        income_keywords = ["invoice", "payment from", "salary", "payroll", "deposit"]
        if any(kw in text for kw in income_keywords):
            return "business"
    
    return "uncertain"