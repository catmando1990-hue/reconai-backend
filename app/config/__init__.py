# app/config/__init__.py
# Re-export from original config.py for backwards compatibility
from typing import Dict

from dotenv import load_dotenv
import os

load_dotenv()

# In-memory storage: user_id -> Plaid access_token
USER_ACCESS_TOKENS: Dict[str, str] = {}

PLAID_CLIENT_ID = os.getenv("PLAID_CLIENT_ID")
PLAID_SECRET = os.getenv("PLAID_SECRET")
PLAID_ENV = os.getenv("PLAID_ENV", "sandbox")

# Phase 67-69 policy flags
from .policy_flags import ENTERPRISE_FLAGS

__all__ = [
    "USER_ACCESS_TOKENS",
    "PLAID_CLIENT_ID",
    "PLAID_SECRET",
    "PLAID_ENV",
    "ENTERPRISE_FLAGS",
]
