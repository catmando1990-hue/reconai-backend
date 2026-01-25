# app/plaid/products.py
"""
Plaid Products Configuration

This module defines all Plaid products that ReconAI requests access to.
Products are categorized by type and availability.

============================================================================
PRODUCT CATEGORIES
============================================================================

1. CORE PRODUCTS (always requested)
   - transactions: Historical and real-time transaction data
   - auth: Account and routing numbers
   - balance: Current balance information (implicit with transactions)

2. EXTENDED PRODUCTS (requested for full financial picture)
   - identity: Account holder information
   - assets: Asset reports
   - investments: Investment account data
   - liabilities: Loan and credit data

3. OPTIONAL PRODUCTS (requested as optional_products)
   - income: Income verification

============================================================================
"""

from __future__ import annotations

import os
from typing import List, Optional

from plaid.model.products import Products
from plaid.model.country_code import CountryCode


# =============================================================================
# PRODUCT DEFINITIONS
# =============================================================================

# Core products - always requested
# Note: balance is implicit when transactions is requested, but we include it
# explicitly to ensure balance data is always available
CORE_PRODUCTS: List[Products] = [
    Products("transactions"),
    Products("auth"),
]

# Extended products - requested for comprehensive financial data
EXTENDED_PRODUCTS: List[Products] = [
    Products("identity"),
    Products("assets"),
    Products("investments"),
    Products("liabilities"),
]

# Optional products - requested via optional_products parameter
# These are products that may not be supported by all institutions
OPTIONAL_PRODUCTS: List[Products] = [
    Products("income"),
]

# Additional products via additional_consented_products
# Reserved for future use
ADDITIONAL_CONSENTED_PRODUCTS: List[Products] = []


def get_products(include_extended: bool = True) -> List[Products]:
    """
    Get the list of Plaid products to request.
    
    Args:
        include_extended: Whether to include extended products
        
    Returns:
        List of Products to request in Link token
    """
    products = CORE_PRODUCTS.copy()
    if include_extended:
        products.extend(EXTENDED_PRODUCTS)
    return products


def get_optional_products() -> List[Products]:
    """Get optional products to request."""
    return OPTIONAL_PRODUCTS.copy()


def get_additional_consented_products() -> List[Products]:
    """Get additional consented products."""
    return ADDITIONAL_CONSENTED_PRODUCTS.copy()


# =============================================================================
# COUNTRY CONFIGURATION
# =============================================================================

SUPPORTED_COUNTRIES: List[CountryCode] = [
    CountryCode("US"),
]


def get_country_codes() -> List[CountryCode]:
    """Get supported country codes."""
    return SUPPORTED_COUNTRIES.copy()


# =============================================================================
# WEBHOOK CONFIGURATION
# =============================================================================

def get_webhook_url() -> Optional[str]:
    """
    Get the configured webhook URL.
    
    Environment variables checked (in order):
    1. PLAID_WEBHOOK_URL - Direct webhook URL
    2. PLAID_WEBHOOK_BASE_URL + /api/plaid/v3/webhook
    3. API_BASE_URL + /api/plaid/v3/webhook
    
    Returns:
        Webhook URL or None if not configured
    """
    # Direct webhook URL (highest priority)
    webhook_url = os.getenv("PLAID_WEBHOOK_URL")
    if webhook_url:
        return webhook_url
    
    # Base URL + path
    base_url = os.getenv("PLAID_WEBHOOK_BASE_URL") or os.getenv("API_BASE_URL")
    if base_url:
        return f"{base_url.rstrip('/')}/api/plaid/v3/webhook"
    
    return None


# =============================================================================
# LINK TOKEN OPTIONS
# =============================================================================

def get_link_token_options() -> dict:
    """
    Get additional options for link token creation.
    
    Returns:
        Dict of options to pass to LinkTokenCreateRequest
    """
    options = {}
    
    # Redirect URI for OAuth flows
    redirect_uri = os.getenv("PLAID_REDIRECT_URI")
    if redirect_uri:
        options["redirect_uri"] = redirect_uri
    
    # Webhook URL
    webhook_url = get_webhook_url()
    if webhook_url:
        options["webhook"] = webhook_url
    
    return options


# =============================================================================
# PRODUCT READINESS CHECK
# =============================================================================

# Products that require async processing and may not be immediately available
ASYNC_PRODUCTS = frozenset([
    "assets",
    "income",
    "income_verification",
])


def is_async_product(product: str) -> bool:
    """
    Check if a product requires async processing.
    
    Async products may not be immediately available after token exchange.
    The frontend should wait for webhook notification before fetching.
    
    Args:
        product: Product name
        
    Returns:
        True if product is async
    """
    return product.lower() in ASYNC_PRODUCTS


# Products available immediately after token exchange
IMMEDIATELY_AVAILABLE_PRODUCTS = frozenset([
    "transactions",
    "auth",
    "balance",
    "identity",
    "investments",
    "liabilities",
])


def is_immediately_available(product: str) -> bool:
    """
    Check if a product is immediately available after token exchange.
    
    Args:
        product: Product name
        
    Returns:
        True if product data can be fetched immediately
    """
    return product.lower() in IMMEDIATELY_AVAILABLE_PRODUCTS


# =============================================================================
# PRODUCT DESCRIPTIONS (for UI display)
# =============================================================================

PRODUCT_DESCRIPTIONS = {
    "transactions": "Access to transaction history and real-time updates",
    "auth": "Account and routing numbers for ACH transfers",
    "balance": "Current account balance information",
    "identity": "Account holder name, address, and contact information",
    "assets": "Comprehensive asset reports for lending decisions",
    "investments": "Investment holdings and transaction history",
    "liabilities": "Credit cards, loans, and mortgage information",
    "income": "Income verification and employment data",
}


def get_product_description(product: str) -> str:
    """Get a user-friendly description for a product."""
    return PRODUCT_DESCRIPTIONS.get(product.lower(), f"Access to {product} data")
