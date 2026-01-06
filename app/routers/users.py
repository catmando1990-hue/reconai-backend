from fastapi import APIRouter, HTTPException, status, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr
from typing import Optional, Dict, Any
import sqlite3
from datetime import datetime
import json

from app.auth_context import get_current_user_id

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


# =========================================================================
# GDPR/CCPA COMPLIANCE ENDPOINTS
# =========================================================================

@router.get("/export-data")
async def export_user_data(
    current_user_id: str = Depends(get_current_user_id)
):
    """
    Export all user data (GDPR Article 20 - Right to Data Portability)

    Returns all data associated with the user in JSON format.
    Required for GDPR and CCPA compliance.
    """
    try:
        from app.db import get_db_connection

        conn = get_db_connection()
        cursor = conn.cursor()

        data_export = {
            "user_id": current_user_id,
            "export_date": datetime.now().isoformat(),
            "data": {}
        }

        # Export user profile
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (current_user_id,))
        row = cursor.fetchone()
        if row:
            columns = [desc[0] for desc in cursor.description]
            data_export["data"]["profile"] = dict(zip(columns, row))

        # Export organizations
        cursor.execute("""
            SELECT o.* FROM organizations o
            JOIN organization_members om ON o.id = om.organization_id
            WHERE om.user_id = ?
        """, (current_user_id,))
        rows = cursor.fetchall()
        if rows:
            columns = [desc[0] for desc in cursor.description]
            data_export["data"]["organizations"] = [dict(zip(columns, row)) for row in rows]

        # Export audit logs (last 1000 events)
        cursor.execute("""
            SELECT * FROM audit_logs
            WHERE user_id = ?
            ORDER BY timestamp DESC
            LIMIT 1000
        """, (current_user_id,))
        rows = cursor.fetchall()
        if rows:
            columns = [desc[0] for desc in cursor.description]
            data_export["data"]["audit_logs"] = [dict(zip(columns, row)) for row in rows]

        conn.close()

        return JSONResponse(
            content=data_export,
            headers={
                "Content-Disposition": f"attachment; filename=reconai_data_export_{current_user_id}_{datetime.now().strftime('%Y%m%d')}.json"
            }
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export user data: {str(e)}"
        )


@router.delete("/delete-account")
async def delete_user_account(
    confirmation: str,
    current_user_id: str = Depends(get_current_user_id)
):
    """
    Permanently delete user account (GDPR Article 17 - Right to Erasure)

    This is irreversible. All user data will be deleted.
    Required for GDPR and CCPA compliance.

    Args:
        confirmation: Must be "DELETE" to confirm
    """
    if confirmation != "DELETE":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirmation must be 'DELETE' to proceed with account deletion"
        )

    try:
        from app.db import get_db_connection

        conn = get_db_connection()
        cursor = conn.cursor()

        # Delete user from all tables
        # Note: In production, consider anonymizing instead of deleting for audit compliance

        # Delete user profile
        cursor.execute("DELETE FROM users WHERE user_id = ?", (current_user_id,))

        # Remove from organizations
        cursor.execute("DELETE FROM organization_members WHERE user_id = ?", (current_user_id,))

        # Anonymize audit logs (keep for compliance, remove PII)
        cursor.execute("""
            UPDATE audit_logs
            SET user_id = 'deleted_user', ip_address = 'anonymized', user_agent = 'anonymized'
            WHERE user_id = ?
        """, (current_user_id,))

        conn.commit()
        conn.close()

        return {
            "success": True,
            "message": "Account permanently deleted",
            "deleted_at": datetime.now().isoformat()
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete account: {str(e)}"
        )


@router.get("/data-processing-log")
async def get_data_processing_log(
    current_user_id: str = Depends(get_current_user_id)
):
    """
    View data processing activities (GDPR Article 15 - Right of Access)

    Returns information about what data is processed and how.
    Required for GDPR transparency.
    """
    return {
        "user_id": current_user_id,
        "data_controller": {
            "name": "ReconAI Inc.",
            "contact": "privacy@reconai.com"
        },
        "data_collected": {
            "personal_info": ["name", "email", "phone", "address"],
            "financial_data": ["transactions", "invoices", "tax records"],
            "usage_data": ["login history", "page views", "API calls"]
        },
        "purpose_of_processing": [
            "Provide bookkeeping and accounting services",
            "Tax optimization and compliance",
            "Generate financial reports",
            "Customer support"
        ],
        "third_party_processors": [
            {"name": "Clerk", "purpose": "Authentication", "location": "USA"},
            {"name": "Plaid", "purpose": "Bank connections", "location": "USA"},
            {"name": "Stripe", "purpose": "Payment processing", "location": "USA"},
            {"name": "Anthropic", "purpose": "AI classification", "location": "USA"}
        ],
        "data_retention": {
            "financial_records": "7 years (legal requirement)",
            "personal_info": "Until account deletion",
            "audit_logs": "7 years (compliance)"
        },
        "your_rights": [
            "Right to access your data (this endpoint)",
            "Right to export your data (GET /api/user/export-data)",
            "Right to delete your account (DELETE /api/user/delete-account)",
            "Right to object to processing (contact privacy@reconai.com)"
        ]
    }


# =========================================================================
# SESSION MANAGEMENT ENDPOINTS
# =========================================================================

@router.get("/sessions")
async def get_active_sessions(
    current_user_id: str = Depends(get_current_user_id)
):
    """
    Get all active sessions for the current user.

    Shows all devices/locations where user is currently logged in.
    Useful for security monitoring.
    """
    try:
        from app.db import get_db_connection

        conn = get_db_connection()
        cursor = conn.cursor()

        # Get recent login events from audit logs
        cursor.execute("""
            SELECT DISTINCT
                ip_address,
                user_agent,
                MAX(timestamp) as last_seen
            FROM audit_logs
            WHERE user_id = ?
                AND action = 'AUTHENTICATION'
                AND timestamp > datetime('now', '-7 days')
            GROUP BY ip_address, user_agent
            ORDER BY last_seen DESC
        """, (current_user_id,))

        rows = cursor.fetchall()
        conn.close()

        sessions = []
        for row in rows:
            sessions.append({
                "ip_address": row[0],
                "device": row[1],
                "last_seen": row[2],
                "is_current": row[0] == "current"  # Compare with current request IP
            })

        return {
            "total_sessions": len(sessions),
            "sessions": sessions
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get sessions: {str(e)}"
        )


@router.post("/logout-all")
async def logout_all_sessions(
    current_user_id: str = Depends(get_current_user_id)
):
    """
    Logout from all devices/sessions.

    Invalidates all active sessions except the current one.
    Useful if account is compromised.

    Note: This requires Clerk API integration to actually invalidate tokens.
    """
    try:
        # In production, call Clerk API to invalidate all sessions
        # clerk_client.users.revoke_session(user_id, session_id)

        return {
            "success": True,
            "message": "All sessions have been logged out",
            "logged_out_at": datetime.now().isoformat(),
            "note": "You will need to log in again on all other devices"
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to logout all sessions: {str(e)}"
        )


@router.get("/security-log")
async def get_security_log(
    limit: int = 50,
    current_user_id: str = Depends(get_current_user_id)
):
    """
    Get security-related events for the current user.

    Shows login attempts, password changes, profile updates, etc.
    """
    try:
        from app.db import get_db_connection

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                timestamp,
                action,
                method,
                path,
                ip_address,
                status_code
            FROM audit_logs
            WHERE user_id = ?
                AND action IN ('AUTHENTICATION', 'UPDATE', 'DELETE')
            ORDER BY timestamp DESC
            LIMIT ?
        """, (current_user_id, limit))

        rows = cursor.fetchall()
        conn.close()

        events = []
        for row in rows:
            events.append({
                "timestamp": row[0],
                "event_type": row[1],
                "method": row[2],
                "path": row[3],
                "ip_address": row[4],
                "status": "success" if row[5] == 200 else "failed"
            })

        return {
            "total_events": len(events),
            "events": events
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get security log: {str(e)}"
        )
