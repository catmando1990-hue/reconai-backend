# ReconAI Backend

## Project Overview
ReconAI is an AI-powered financial intelligence platform for veteran-owned businesses and government contractors. This is the FastAPI backend that handles data processing, AI classification, and integrations.

## Tech Stack
- **Framework:** FastAPI
- **Language:** Python 3.11+
- **Database:** SQLite (local) / PostgreSQL (Supabase production)
- **AI:** Anthropic Claude API for transaction classification
- **Banking:** Plaid API
- **Payments:** Stripe
- **Auth Verification:** Clerk JWT validation
- **Error Monitoring:** Sentry
- **Deployment:** Render

## Project Structure
\\\
reconai-backend/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app, middleware, routes
│   ├── config.py            # Configuration
│   ├── db.py                # Database setup and queries
│   ├── models.py            # Pydantic models
│   ├── models_multitenancy.py # Multi-tenant models
│   ├── middleware.py        # Rate limiting middleware
│   ├── plaid_client.py      # Plaid integration
│   ├── stores.py            # Data stores
│   ├── feedback.py          # Feedback handling
│   ├── bookkeeping/
│   │   └── engine.py        # Bookkeeping engine
│   ├── routers/
│   │   ├── auth.py          # Authentication routes
│   │   ├── users.py         # User management
│   │   ├── organizations.py # Organization management
│   │   ├── entities.py      # Business entities
│   │   ├── vendors.py       # Vendor management
│   │   ├── customers.py     # Customer management
│   │   ├── invoices.py      # Invoice management
│   │   ├── plaid.py         # Plaid/classification routes
│   │   ├── transactions.py  # Transaction routes
│   │   ├── bookkeeping.py   # Bookkeeping routes
│   │   ├── accounting.py    # Accounting routes
│   │   ├── tax.py           # Tax routes
│   │   ├── credit.py        # Credit routes
│   │   ├── reports.py       # Report generation
│   │   ├── compliance.py    # DCAA compliance
│   │   ├── contact.py       # Contact form
│   │   ├── newsletter.py    # Newsletter signup
│   │   ├── feedback.py      # User feedback
│   │   ├── files.py         # File uploads
│   │   ├── exports.py       # Data exports
│   │   ├── reconai.py       # Core ReconAI routes
│   │   ├── stripe_webhooks.py # Stripe webhooks
│   │   └── claude.py        # Claude AI routes
│   └── services/
│       └── organization_service.py
├── data/                    # SQLite database files
├── tests/                   # Test files
├── venv/                    # Python virtual environment
├── requirements.txt         # Python dependencies
├── .env                     # Environment variables
└── render.yaml              # Render deployment config
\\\

## Frontend Communication
The backend serves the Next.js frontend at:
- **Local Frontend:** http://localhost:3000 or http://localhost:3001
- **Production Frontend:** https://reconai-frontend.vercel.app

### CORS Configuration
\\\python
# Allowed origins in main.py
origins = [
    "http://localhost:3000",
    "http://localhost:3001",
    "http://localhost:5173",
    "https://reconai-frontend.vercel.app",
    "https://*.vercel.app",  # Preview deployments
]
\\\

## API Endpoints

### Core Classification
\\\python
POST /classify-transactions
# Classifies bank transactions using AI
# Body: { transactions: [...] }
# Returns: { classified: [...] }
\\\

### Authentication (Clerk JWT)
\\\python
GET  /api/auth/verify     # Verify Clerk token
POST /api/users/sync      # Sync user from Clerk
\\\

### Plaid Integration
\\\python
POST /api/plaid/create-link-token
POST /api/plaid/exchange-public-token
GET  /api/plaid/accounts
GET  /api/plaid/transactions
\\\

### Organizations & Entities
\\\python
GET  /api/organizations
POST /api/organizations
GET  /api/organizations/{id}
PUT  /api/organizations/{id}

GET  /api/entities
POST /api/entities
\\\

### Bookkeeping
\\\python
GET  /api/bookkeeping/chart-of-accounts
POST /api/bookkeeping/journal-entries
GET  /api/bookkeeping/ledger
GET  /api/bookkeeping/trial-balance
\\\

### Reports
\\\python
GET  /api/reports
POST /api/reports/generate
GET  /api/reports/{id}/download
\\\

### Compliance (DCAA)
\\\python
GET  /api/compliance/status
GET  /api/compliance/dcaa-report
\\\

## Environment Variables
\\\ash
# Database
DB_PATH=./data/reconai.db
DATA_DIR=./data

# Anthropic AI
ANTHROPIC_API_KEY=sk-ant-...

# Plaid
PLAID_CLIENT_ID=...
PLAID_SECRET=...
PLAID_ENV=sandbox  # or development, production

# Stripe
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...

# Clerk (for JWT verification)
CLERK_SECRET_KEY=sk_test_...

# Supabase (production DB)
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJ...

# Sentry
SENTRY_DSN=https://...

# Environment
ENVIRONMENT=development  # or production
\\\

## Key Patterns

### Route Pattern
\\\python
from fastapi import APIRouter, Depends, HTTPException
from app.models import RequestModel, ResponseModel

router = APIRouter(prefix="/api/resource", tags=["resource"])

@router.get("/")
async def list_items():
    return {"items": []}

@router.post("/", response_model=ResponseModel)
async def create_item(data: RequestModel):
    # Process and return
    return ResponseModel(...)
\\\

### Clerk Auth Verification
\\\python
import jwt
from fastapi import Depends, HTTPException, Header

async def verify_clerk_token(authorization: str = Header(...)):
    try:
        token = authorization.replace("Bearer ", "")
        # Verify with Clerk's public key
        payload = jwt.decode(token, options={"verify_signature": False})
        return payload
    except:
        raise HTTPException(status_code=401, detail="Invalid token")
\\\

### AI Classification Pattern
\\\python
import anthropic

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

def classify_transaction(transaction: dict) -> dict:
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": f"Classify this transaction: {transaction}"
        }]
    )
    return parse_classification(response.content[0].text)
\\\

## Common Commands
\\\ash
# Activate virtual environment
cd C:\reconai-backend
.\venv\Scripts\Activate

# Run development server
uvicorn app.main:app --reload --port 8000

# Install dependencies
pip install -r requirements.txt

# Update requirements
pip freeze > requirements.txt

# Run tests
pytest

# Deploy (auto via Render on git push)
git push origin feature/clerk-auth
\\\

## Database Schema

### Key Tables
\\\sql
-- Users (synced from Clerk)
users (id, clerk_id, email, name, created_at)

-- Organizations
organizations (id, name, owner_id, settings, created_at)

-- Transactions
transactions (id, org_id, date, description, amount, category, confidence)

-- Chart of Accounts
accounts (id, org_id, code, name, type, parent_id)

-- Journal Entries
journal_entries (id, org_id, date, description, entries_json)

-- Invoices
invoices (id, org_id, customer_id, number, amount, status, due_date)
\\\

## Related Projects
- **Frontend:** C:\reconai-frontend (Next.js)
- **Frontend Repo:** github.com/catmando1990-hue/reconai-frontend
- **Production Frontend:** https://reconai-frontend.vercel.app
- **Production Backend:** https://reconai-backend.onrender.com
