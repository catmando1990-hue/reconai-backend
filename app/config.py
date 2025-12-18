# app/config.py

from typing import Dict

# In-memory storage: user_id -> Plaid access_token
USER_ACCESS_TOKENS: Dict[str, str] = {}

from dotenv import load_dotenv
import os

load_dotenv()

PLAID_CLIENT_ID = os.getenv("PLAID_CLIENT_ID")
PLAID_SECRET = os.getenv("PLAID_SECRET")
PLAID_ENV = os.getenv("PLAID_ENV", "sandbox")
