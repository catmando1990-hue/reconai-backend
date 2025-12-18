# app/plaid_client.py
from typing import Dict

from plaid.api import plaid_api
from plaid.configuration import Configuration, Environment

from .config import PLAID_CLIENT_ID, PLAID_SECRET, PLAID_ENV

# In-memory storage: user_id -> Plaid access_token
USER_ACCESS_TOKENS: Dict[str, str] = {}


def get_plaid_client() -> plaid_api.PlaidApi:
    """Create and return a Plaid client configured from environment variables."""
    if not PLAID_CLIENT_ID or not PLAID_SECRET:
        raise RuntimeError("PLAID_CLIENT_ID or PLAID_SECRET not set in your .env file")

    if PLAID_ENV == "sandbox":
        environment = Environment.Sandbox
    elif PLAID_ENV == "development":
        environment = Environment.Development
    else:
        environment = Environment.Production

    config = Configuration(
        host=environment,
        api_key={
            "clientId": PLAID_CLIENT_ID,
            "secret": PLAID_SECRET,
        },
    )

    api_client = plaid_api.ApiClient(config)
    return plaid_api.PlaidApi(api_client)
