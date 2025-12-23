from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, EmailStr
from typing import Optional
import sqlite3
from datetime import datetime

try:
    from .auth import get_current_user_id
except ImportError:
    def get_current_user_id():
        return "system"

router = APIRouter(prefix="/api/user", tags=["users"])

# =========================================================================
# MODELS
# =========================================================================

class UserProfile(BaseModel):
    """User profile information"""
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    company: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    country: Optional[str] = "USA"
    timezone: Optional[str] = "America/New_York"

class NotificationSettings(BaseModel):
    """User notification preferences"""
    email_notifications: bool = True
    transaction_alerts: bool = True
    compliance_alerts: bool = True
    invoice_reminders: bool = True
    weekly_summary: bool = True
    monthly_report: bool = True

class UpdateProfileRequest(BaseModel):
    """Update user profile request"""
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    company: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    country: Optional[str] = None
    timezone: Optional[str] = None

class UpdateNotificationsRequest(BaseModel):
    """Update notification settings request"""
    email_notifications: Optional[bool] = None
    transaction_alerts: Optional[bool] = None
    compliance_alerts: Optional[bool] = None
    invoice_reminders: Optional[bool] = None
    weekly_summary: Optional[bool] = None
    monthly_report: Optional[bool] = None


# =========================================================================
# ENDPOINTS
# =========================================================================

@router.get("/profile", response_model=UserProfile)
async def get_user_profile(
    current_user_id: str = Depends(get_current_user_id)
):
    """
    Get current user's profile

    Returns user profile information including:
    - Personal information (name, email, phone)
    - Company details
    - Address information
    - Preferences (timezone)
    """
    try:
        from app.db import get_db_connection

        conn = get_db_connection()
        cursor = conn.cursor()

        # Get user profile from users table
        cursor.execute("""
            SELECT
                full_name,
                email,
                company_name,
                phone,
                address,
                city,
                state,
                zip_code,
                country,
                timezone
            FROM users
            WHERE user_id = ?
        """, (current_user_id,))

        row = cursor.fetchone()
        conn.close()

        if not row:
            # Return empty profile if user not found (will be created on first update)
            return UserProfile()

        return UserProfile(
            name=row[0],
            email=row[1],
            company=row[2],
            phone=row[3],
            address=row[4],
            city=row[5],
            state=row[6],
            zip=row[7],
            country=row[8],
            timezone=row[9]
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get user profile: {str(e)}"
        )


@router.put("/profile", response_model=UserProfile)
async def update_user_profile(
    profile: UpdateProfileRequest,
    current_user_id: str = Depends(get_current_user_id)
):
    """
    Update current user's profile

    Updates user profile information. Creates user record if it doesn't exist.
    """
    try:
        from app.db import get_db_connection

        conn = get_db_connection()
        cursor = conn.cursor()

        # Check if user exists
        cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (current_user_id,))
        exists = cursor.fetchone()

        if not exists:
            # Create new user record
            cursor.execute("""
                INSERT INTO users (
                    user_id, full_name, email, company_name, phone,
                    address, city, state, zip_code, country, timezone, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                current_user_id,
                profile.name,
                profile.email,
                profile.company,
                profile.phone,
                profile.address,
                profile.city,
                profile.state,
                profile.zip,
                profile.country or "USA",
                profile.timezone or "America/New_York",
                datetime.now().isoformat()
            ))
        else:
            # Build update query dynamically based on provided fields
            updates = []
            params = []

            if profile.name is not None:
                updates.append("full_name = ?")
                params.append(profile.name)
            if profile.email is not None:
                updates.append("email = ?")
                params.append(profile.email)
            if profile.company is not None:
                updates.append("company_name = ?")
                params.append(profile.company)
            if profile.phone is not None:
                updates.append("phone = ?")
                params.append(profile.phone)
            if profile.address is not None:
                updates.append("address = ?")
                params.append(profile.address)
            if profile.city is not None:
                updates.append("city = ?")
                params.append(profile.city)
            if profile.state is not None:
                updates.append("state = ?")
                params.append(profile.state)
            if profile.zip is not None:
                updates.append("zip_code = ?")
                params.append(profile.zip)
            if profile.country is not None:
                updates.append("country = ?")
                params.append(profile.country)
            if profile.timezone is not None:
                updates.append("timezone = ?")
                params.append(profile.timezone)

            if updates:
                updates.append("updated_at = ?")
                params.append(datetime.now().isoformat())
                params.append(current_user_id)

                query = f"UPDATE users SET {', '.join(updates)} WHERE user_id = ?"
                cursor.execute(query, params)

        conn.commit()

        # Fetch updated profile
        cursor.execute("""
            SELECT
                full_name, email, company_name, phone, address,
                city, state, zip_code, country, timezone
            FROM users
            WHERE user_id = ?
        """, (current_user_id,))

        row = cursor.fetchone()
        conn.close()

        return UserProfile(
            name=row[0],
            email=row[1],
            company=row[2],
            phone=row[3],
            address=row[4],
            city=row[5],
            state=row[6],
            zip=row[7],
            country=row[8],
            timezone=row[9]
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update user profile: {str(e)}"
        )


@router.get("/notifications", response_model=NotificationSettings)
async def get_notification_settings(
    current_user_id: str = Depends(get_current_user_id)
):
    """
    Get current user's notification preferences

    Returns notification settings for:
    - Email notifications
    - Transaction alerts
    - Compliance alerts
    - Invoice reminders
    - Weekly summary
    - Monthly report
    """
    try:
        from app.db import get_db_connection

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                email_notifications,
                transaction_alerts,
                compliance_alerts,
                invoice_reminders,
                weekly_summary,
                monthly_report
            FROM users
            WHERE user_id = ?
        """, (current_user_id,))

        row = cursor.fetchone()
        conn.close()

        if not row:
            # Return default settings if user not found
            return NotificationSettings()

        return NotificationSettings(
            email_notifications=bool(row[0]) if row[0] is not None else True,
            transaction_alerts=bool(row[1]) if row[1] is not None else True,
            compliance_alerts=bool(row[2]) if row[2] is not None else True,
            invoice_reminders=bool(row[3]) if row[3] is not None else True,
            weekly_summary=bool(row[4]) if row[4] is not None else True,
            monthly_report=bool(row[5]) if row[5] is not None else True
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get notification settings: {str(e)}"
        )


@router.put("/notifications", response_model=NotificationSettings)
async def update_notification_settings(
    settings: UpdateNotificationsRequest,
    current_user_id: str = Depends(get_current_user_id)
):
    """
    Update current user's notification preferences

    Updates notification settings. Only provided fields will be updated.
    """
    try:
        from app.db import get_db_connection

        conn = get_db_connection()
        cursor = conn.cursor()

        # Build update query dynamically
        updates = []
        params = []

        if settings.email_notifications is not None:
            updates.append("email_notifications = ?")
            params.append(int(settings.email_notifications))
        if settings.transaction_alerts is not None:
            updates.append("transaction_alerts = ?")
            params.append(int(settings.transaction_alerts))
        if settings.compliance_alerts is not None:
            updates.append("compliance_alerts = ?")
            params.append(int(settings.compliance_alerts))
        if settings.invoice_reminders is not None:
            updates.append("invoice_reminders = ?")
            params.append(int(settings.invoice_reminders))
        if settings.weekly_summary is not None:
            updates.append("weekly_summary = ?")
            params.append(int(settings.weekly_summary))
        if settings.monthly_report is not None:
            updates.append("monthly_report = ?")
            params.append(int(settings.monthly_report))

        if updates:
            updates.append("updated_at = ?")
            params.append(datetime.now().isoformat())
            params.append(current_user_id)

            query = f"UPDATE users SET {', '.join(updates)} WHERE user_id = ?"
            cursor.execute(query, params)
            conn.commit()

        # Fetch updated settings
        cursor.execute("""
            SELECT
                email_notifications, transaction_alerts, compliance_alerts,
                invoice_reminders, weekly_summary, monthly_report
            FROM users
            WHERE user_id = ?
        """, (current_user_id,))

        row = cursor.fetchone()
        conn.close()

        return NotificationSettings(
            email_notifications=bool(row[0]) if row[0] is not None else True,
            transaction_alerts=bool(row[1]) if row[1] is not None else True,
            compliance_alerts=bool(row[2]) if row[2] is not None else True,
            invoice_reminders=bool(row[3]) if row[3] is not None else True,
            weekly_summary=bool(row[4]) if row[4] is not None else True,
            monthly_report=bool(row[5]) if row[5] is not None else True
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update notification settings: {str(e)}"
        )
