# app/routers/auth.py

"""
Authentication API - Clerk Integration
Handles user authentication, session management, and JWT validation
"""

from fastapi import APIRouter, HTTPException, Depends, Header, status
from pydantic import BaseModel, EmailStr
from typing import Optional
import os
import jwt
from jwt import PyJWKClient
from functools import lru_cache

from ..services.organization_service import OrganizationService
from ..services.email_service import email_service, EmailRecipient
from ..models_multitenancy import User, SubscriptionTier, Industry
from ..db import DB_PATH

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

# =========================================================================
# CLERK CONFIGURATION
# =========================================================================

CLERK_SECRET_KEY = os.getenv("CLERK_SECRET_KEY", "")
CLERK_PUBLISHABLE_KEY = os.getenv("CLERK_PUBLISHABLE_KEY", "")
CLERK_JWKS_URL = os.getenv("CLERK_JWKS_URL", "https://api.clerk.com/v1/jwks")

# =========================================================================
# REQUEST/RESPONSE MODELS
# =========================================================================

class SignupRequest(BaseModel):
    """Request to create new user account with organization"""
    email: EmailStr
    clerk_user_id: str  # From Clerk after OAuth/signup
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    organization_name: str
    organization_slug: str
    tier: SubscriptionTier = SubscriptionTier.INDIVIDUAL
    industry: Optional[Industry] = None

class UserResponse(BaseModel):
    """User profile response"""
    id: str
    email: str
    first_name: Optional[str]
    last_name: Optional[str]
    avatar_url: Optional[str]
    default_org_id: Optional[str]
    is_active: bool
    email_verified: bool
    created_at: str

    class Config:
        from_attributes = True

class AuthResponse(BaseModel):
    """Authentication response"""
    user: UserResponse
    organization_id: str
    message: str

# =========================================================================
# JWT VALIDATION
# =========================================================================

@lru_cache()
def get_jwks_client():
    """Get cached JWKS client for Clerk JWT validation"""
    if not CLERK_JWKS_URL:
        raise ValueError("CLERK_JWKS_URL not configured")
    return PyJWKClient(CLERK_JWKS_URL)

def verify_clerk_token(token: str) -> dict:
    """
    Verify Clerk JWT token and return decoded payload

    Returns:
        dict: Decoded JWT payload with user claims

    Raises:
        HTTPException: If token is invalid or expired
    """
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No authentication token provided"
        )

    try:
        # Get signing key from Clerk JWKS
        jwks_client = get_jwks_client()
        signing_key = jwks_client.get_signing_key_from_jwt(token)

        # Verify and decode token
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            options={"verify_exp": True}
        )

        return payload

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired"
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Token verification failed: {str(e)}"
        )

# =========================================================================
# DEPENDENCY INJECTION
# =========================================================================

def get_org_service() -> OrganizationService:
    """Dependency: Get organization service instance"""
    return OrganizationService(DB_PATH)

async def get_current_user(
    authorization: Optional[str] = Header(None),
    service: OrganizationService = Depends(get_org_service)
) -> User:
    """
    Dependency: Get current authenticated user from JWT

    Expects Authorization header: "Bearer <token>"
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header"
        )

    # Extract token from "Bearer <token>"
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format. Expected: Bearer <token>"
        )

    token = parts[1]

    # Verify token with Clerk
    payload = verify_clerk_token(token)

    # Get user_id from JWT claims
    # Clerk uses 'sub' claim for user ID
    clerk_user_id = payload.get("sub")
    if not clerk_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: missing user ID"
        )

    # Look up user in our database by Clerk user ID
    # We'll need to add clerk_user_id field to users table
    # For now, use email from JWT
    email = payload.get("email")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: missing email"
        )

    user = service.get_user_by_email(email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found. Please complete signup."
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive"
        )

    return user

async def get_current_user_id(
    current_user: User = Depends(get_current_user)
) -> str:
    """Dependency: Get current user ID"""
    return current_user.id

async def get_current_organization_id(
    authorization: Optional[str] = Header(None)
) -> str:
    """
    Dependency: Get current organization ID from JWT or header

    For now, returns a default organization ID.
    TODO: Extract from JWT or require X-Organization-ID header
    """
    # Temporary: return a default organization ID
    # In production, this should be extracted from the JWT or require an X-Organization-ID header
    return "default-org-id"

# =========================================================================
# AUTHENTICATION ENDPOINTS
# =========================================================================

@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def signup(
    request: SignupRequest,
    service: OrganizationService = Depends(get_org_service)
):
    """
    Complete user signup after Clerk authentication

    Flow:
    1. User signs up via Clerk (OAuth/email)
    2. Frontend receives Clerk user ID
    3. Frontend calls this endpoint to create ReconAI user + org
    4. User can now access the application
    """
    try:
        # Check if user already exists
        existing_user = service.get_user_by_email(request.email)
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User already exists. Please login instead."
            )

        # Check if org slug is available
        existing_org = service.get_organization_by_slug(request.organization_slug)
        if existing_org:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Organization slug '{request.organization_slug}' is already taken"
            )

        # Create organization with owner user
        org, user = service.create_organization(
            name=request.organization_name,
            slug=request.organization_slug,
            owner_email=request.email,
            tier=request.tier,
            industry=request.industry.value if request.industry else None
        )

        # Update user with Clerk details
        # TODO: Add update_user method to service that includes clerk_user_id, first_name, last_name
        import sqlite3
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                UPDATE users
                SET first_name = ?, last_name = ?, email_verified = 1
                WHERE id = ?
            """, (request.first_name, request.last_name, user.id))
            conn.commit()

        # Fetch updated user
        user = service.get_user(user.id)

        # Send welcome email
        try:
            email_service.send_welcome_email(
                to=EmailRecipient(email=user.email, name=user.first_name),
                user_name=user.first_name or user.email.split('@')[0],
                organization_name=org.name,
                tier=org.tier.value
            )
        except Exception as e:
            # Log error but don't fail signup
            print(f"Failed to send welcome email: {str(e)}")

        return AuthResponse(
            user=UserResponse(
                id=user.id,
                email=user.email,
                first_name=user.first_name,
                last_name=user.last_name,
                avatar_url=user.avatar_url,
                default_org_id=user.default_org_id,
                is_active=user.is_active,
                email_verified=user.email_verified,
                created_at=user.created_at.isoformat()
            ),
            organization_id=org.id,
            message=f"Account created successfully with 14-day trial"
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Signup failed: {str(e)}"
        )


@router.get("/me", response_model=UserResponse)
async def get_current_user_profile(
    current_user: User = Depends(get_current_user)
):
    """
    Get current authenticated user's profile

    Requires valid JWT in Authorization header
    """
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        first_name=current_user.first_name,
        last_name=current_user.last_name,
        avatar_url=current_user.avatar_url,
        default_org_id=current_user.default_org_id,
        is_active=current_user.is_active,
        email_verified=current_user.email_verified,
        created_at=current_user.created_at.isoformat()
    )


@router.post("/verify")
async def verify_token(
    authorization: Optional[str] = Header(None)
):
    """
    Verify JWT token validity

    Returns decoded token payload if valid
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header"
        )

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format"
        )

    token = parts[1]
    payload = verify_clerk_token(token)

    return {
        "valid": True,
        "user_id": payload.get("sub"),
        "email": payload.get("email"),
        "exp": payload.get("exp")
    }


@router.get("/session")
async def get_session_info(
    current_user: User = Depends(get_current_user),
    service: OrganizationService = Depends(get_org_service)
):
    """
    Get current session information including user and default organization
    """
    # Get user's default organization
    default_org = None
    if current_user.default_org_id:
        default_org = service.get_organization(current_user.default_org_id)

    # Get all user's organizations
    orgs = service.list_user_organizations(current_user.id)

    return {
        "user": {
            "id": current_user.id,
            "email": current_user.email,
            "first_name": current_user.first_name,
            "last_name": current_user.last_name,
            "avatar_url": current_user.avatar_url,
            "email_verified": current_user.email_verified
        },
        "default_organization": {
            "id": default_org.id,
            "name": default_org.name,
            "slug": default_org.slug,
            "tier": default_org.tier.value,
            "features": default_org.features.model_dump()
        } if default_org else None,
        "organizations": [
            {
                "id": org.id,
                "name": org.name,
                "slug": org.slug,
                "tier": org.tier.value
            }
            for org in orgs
        ]
    }
