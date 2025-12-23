# app/routers/newsletter.py

"""
Newsletter & Waitlist API
Handles email subscriptions from marketing site
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from typing import Optional
import sqlite3
import uuid
from datetime import datetime

from ..services.email_service import email_service, EmailRecipient
from ..db import DB_PATH

router = APIRouter(prefix="/api/newsletter", tags=["Newsletter"])


# =========================================================================
# MODELS
# =========================================================================

class NewsletterSignupRequest(BaseModel):
    """Newsletter/waitlist signup"""
    email: EmailStr
    source: str = Field(default="website", description="Where they signed up (website, footer, popup, etc.)")
    list_type: str = Field(default="general", description="Which list (general, waitlist, updates)")
    name: Optional[str] = Field(None, max_length=100)


class NewsletterResponse(BaseModel):
    """Response after newsletter signup"""
    success: bool
    message: str
    already_subscribed: bool = False


class UnsubscribeRequest(BaseModel):
    """Unsubscribe request"""
    email: EmailStr


# =========================================================================
# ENDPOINTS
# =========================================================================

@router.post("/subscribe", response_model=NewsletterResponse, status_code=status.HTTP_201_CREATED)
async def subscribe_newsletter(request: NewsletterSignupRequest):
    """
    Subscribe to newsletter/waitlist

    Handles duplicates gracefully
    """
    try:
        # Check if already subscribed
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.execute("""
                SELECT id, unsubscribed_at FROM newsletter_subscribers
                WHERE email = ? AND list_type = ?
            """, (request.email, request.list_type))
            existing = cursor.fetchone()

            if existing:
                # Already subscribed and active
                if existing[1] is None:
                    return NewsletterResponse(
                        success=True,
                        message="You're already subscribed!",
                        already_subscribed=True
                    )
                else:
                    # Was unsubscribed, resubscribe
                    conn.execute("""
                        UPDATE newsletter_subscribers
                        SET unsubscribed_at = NULL, resubscribed_at = datetime('now')
                        WHERE email = ? AND list_type = ?
                    """, (request.email, request.list_type))
                    conn.commit()

                    return NewsletterResponse(
                        success=True,
                        message="Welcome back! You've been resubscribed.",
                        already_subscribed=False
                    )

            # New subscriber
            subscriber_id = f"subscriber-{uuid.uuid4().hex[:12]}"
            conn.execute("""
                INSERT INTO newsletter_subscribers (
                    id, email, name, source, list_type, subscribed_at
                ) VALUES (?, ?, ?, ?, ?, datetime('now'))
            """, (
                subscriber_id,
                request.email,
                request.name,
                request.source,
                request.list_type
            ))
            conn.commit()

        # Send welcome email
        try:
            welcome_html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                    .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                    .content {{ background: #f9fafb; padding: 30px; border-radius: 0 0 10px 10px; }}
                    .button {{ display: inline-block; background: #667eea; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; margin: 20px 0; }}
                    h1 {{ margin: 0; font-size: 28px; }}
                    .footer {{ text-align: center; margin-top: 30px; color: #666; font-size: 14px; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>Welcome to ReconAI! 🎉</h1>
                    </div>
                    <div class="content">
                        <p>Hi{f" {request.name}" if request.name else ""}!</p>

                        <p>Thanks for subscribing to ReconAI updates. You'll be the first to know about:</p>

                        <ul>
                            <li>✨ New features and updates</li>
                            <li>💡 Financial tips and best practices</li>
                            <li>🎖️ Special offers for veterans</li>
                            <li>📊 Industry insights and trends</li>
                        </ul>

                        <p style="text-align: center;">
                            <a href="https://reconai.com/platform" class="button">Explore ReconAI</a>
                        </p>

                        <p><strong>Get started today:</strong></p>
                        <ul>
                            <li>🚀 <a href="https://app.reconai.com/signup">Start free trial</a></li>
                            <li>📚 <a href="https://docs.reconai.com">Read documentation</a></li>
                            <li>🎥 <a href="https://reconai.com/tutorials">Watch tutorials</a></li>
                        </ul>

                        <p>Looking forward to helping you streamline your finances!</p>

                        <p>Best regards,<br>The ReconAI Team</p>
                    </div>
                    <div class="footer">
                        <p>ReconAI - Financial Intelligence Platform</p>
                        <p>🎖️ 50% off for veteran-owned businesses</p>
                        <p><a href="https://reconai.com/api/newsletter/unsubscribe?email={request.email}">Unsubscribe</a></p>
                    </div>
                </div>
            </body>
            </html>
            """

            email_service.send_email(
                to=EmailRecipient(email=request.email, name=request.name),
                subject="Welcome to ReconAI! 🎉",
                html=welcome_html,
                tags=[{"name": "category", "value": "newsletter_welcome"}]
            )

        except Exception as e:
            print(f"Failed to send welcome email: {str(e)}")

        return NewsletterResponse(
            success=True,
            message="Successfully subscribed! Check your email for confirmation.",
            already_subscribed=False
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to subscribe: {str(e)}"
        )


@router.post("/unsubscribe", response_model=NewsletterResponse)
async def unsubscribe_newsletter(request: UnsubscribeRequest):
    """
    Unsubscribe from newsletter

    Marks as unsubscribed rather than deleting (for compliance)
    """
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.execute("""
                SELECT id FROM newsletter_subscribers
                WHERE email = ? AND unsubscribed_at IS NULL
            """, (request.email,))

            if not cursor.fetchone():
                return NewsletterResponse(
                    success=True,
                    message="Email not found or already unsubscribed.",
                    already_subscribed=False
                )

            # Mark as unsubscribed
            conn.execute("""
                UPDATE newsletter_subscribers
                SET unsubscribed_at = datetime('now')
                WHERE email = ?
            """, (request.email,))
            conn.commit()

        return NewsletterResponse(
            success=True,
            message="You've been unsubscribed. Sorry to see you go!",
            already_subscribed=False
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to unsubscribe: {str(e)}"
        )


@router.get("/unsubscribe")
async def unsubscribe_via_link(email: EmailStr):
    """
    Unsubscribe via email link

    Returns HTML confirmation page
    """
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                UPDATE newsletter_subscribers
                SET unsubscribed_at = datetime('now')
                WHERE email = ?
            """, (email,))
            conn.commit()

        return """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Unsubscribed - ReconAI</title>
            <style>
                body { font-family: Arial, sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; background: #f9fafb; }
                .container { text-align: center; padding: 40px; background: white; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); max-width: 500px; }
                h1 { color: #667eea; }
                p { color: #666; line-height: 1.6; }
                .button { display: inline-block; background: #667eea; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; margin-top: 20px; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>You've been unsubscribed</h1>
                <p>Sorry to see you go! You won't receive any more emails from ReconAI.</p>
                <p>Changed your mind? You can resubscribe anytime.</p>
                <a href="https://reconai.com" class="button">Back to Website</a>
            </div>
        </body>
        </html>
        """

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to unsubscribe: {str(e)}"
        )


@router.get("/subscribers/count")
async def get_subscriber_count():
    """Get total subscriber count (public endpoint)"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.execute("""
                SELECT COUNT(*) FROM newsletter_subscribers
                WHERE unsubscribed_at IS NULL
            """)
            count = cursor.fetchone()[0]

        return {
            "count": count,
            "message": f"Join {count:,} other subscribers!"
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
