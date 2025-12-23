# app/routers/contact.py

"""
Contact Form API
Handles contact form submissions from marketing site
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from typing import Optional
import sqlite3
import uuid
from datetime import datetime

from ..services.email_service import email_service, EmailRecipient
from ..db import DB_PATH

router = APIRouter(prefix="/api/contact", tags=["Contact"])


# =========================================================================
# MODELS
# =========================================================================

class ContactFormRequest(BaseModel):
    """Contact form submission"""
    name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    subject: str = Field(..., min_length=1, max_length=200)
    message: str = Field(..., min_length=10, max_length=5000)
    phone: Optional[str] = Field(None, max_length=20)
    company: Optional[str] = Field(None, max_length=100)
    source: str = Field(default="website", description="Where form was submitted from")


class ContactFormResponse(BaseModel):
    """Response after contact form submission"""
    success: bool
    message: str
    ticket_id: Optional[str] = None


# =========================================================================
# ENDPOINTS
# =========================================================================

@router.post("/", response_model=ContactFormResponse, status_code=status.HTTP_201_CREATED)
async def submit_contact_form(request: ContactFormRequest):
    """
    Submit contact form

    Saves to database and sends email notification to support team
    """
    try:
        # Generate submission ID
        submission_id = f"contact-{uuid.uuid4().hex[:12]}"

        # Save to database
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                INSERT INTO contact_submissions (
                    id, name, email, subject, message, phone, company, source, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """, (
                submission_id,
                request.name,
                request.email,
                request.subject,
                request.message,
                request.phone,
                request.company,
                request.source
            ))
            conn.commit()

        # Send notification email to support team
        try:
            support_email = "support@reconai.com"

            html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                    .header {{ background: #667eea; color: white; padding: 20px; border-radius: 8px 8px 0 0; }}
                    .content {{ background: #f9fafb; padding: 20px; border-radius: 0 0 8px 8px; }}
                    .field {{ margin: 15px 0; }}
                    .label {{ font-weight: bold; color: #666; }}
                    .value {{ margin-top: 5px; }}
                    .message-box {{ background: white; padding: 15px; border-left: 4px solid #667eea; margin: 15px 0; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h2>📧 New Contact Form Submission</h2>
                        <p>ID: {submission_id}</p>
                    </div>
                    <div class="content">
                        <div class="field">
                            <div class="label">Name:</div>
                            <div class="value">{request.name}</div>
                        </div>

                        <div class="field">
                            <div class="label">Email:</div>
                            <div class="value"><a href="mailto:{request.email}">{request.email}</a></div>
                        </div>

                        {f'<div class="field"><div class="label">Phone:</div><div class="value">{request.phone}</div></div>' if request.phone else ''}

                        {f'<div class="field"><div class="label">Company:</div><div class="value">{request.company}</div></div>' if request.company else ''}

                        <div class="field">
                            <div class="label">Subject:</div>
                            <div class="value"><strong>{request.subject}</strong></div>
                        </div>

                        <div class="message-box">
                            <div class="label">Message:</div>
                            <div class="value">{request.message}</div>
                        </div>

                        <div class="field">
                            <div class="label">Source:</div>
                            <div class="value">{request.source}</div>
                        </div>

                        <div class="field">
                            <div class="label">Submitted:</div>
                            <div class="value">{datetime.now().strftime('%B %d, %Y at %I:%M %p')}</div>
                        </div>
                    </div>
                </div>
            </body>
            </html>
            """

            email_service.send_email(
                to=support_email,
                subject=f"Contact Form: {request.subject}",
                html=html,
                reply_to=request.email,
                tags=[{"name": "category", "value": "contact_form"}]
            )

        except Exception as e:
            # Log email error but don't fail the submission
            print(f"Failed to send contact notification email: {str(e)}")

        # Send auto-reply to user
        try:
            auto_reply_html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                    .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                    .content {{ background: #f9fafb; padding: 30px; border-radius: 0 0 10px 10px; }}
                    h1 {{ margin: 0; font-size: 28px; }}
                    .footer {{ text-align: center; margin-top: 30px; color: #666; font-size: 14px; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>Thanks for Reaching Out! 👋</h1>
                    </div>
                    <div class="content">
                        <p>Hi {request.name},</p>

                        <p>We've received your message and our team will get back to you within 24 hours.</p>

                        <p><strong>What you submitted:</strong></p>
                        <p style="background: white; padding: 15px; border-left: 4px solid #667eea;">
                            <strong>Subject:</strong> {request.subject}<br>
                            <strong>Message:</strong> {request.message[:200]}{"..." if len(request.message) > 200 else ""}
                        </p>

                        <p>In the meantime, here are some helpful resources:</p>
                        <ul>
                            <li>📚 <a href="https://docs.reconai.com">Documentation</a></li>
                            <li>💬 <a href="https://support.reconai.com">Help Center</a></li>
                            <li>🎥 <a href="https://reconai.com/tutorials">Video Tutorials</a></li>
                        </ul>

                        <p>Best regards,<br>The ReconAI Team</p>
                    </div>
                    <div class="footer">
                        <p>ReconAI - Financial Intelligence Platform</p>
                        <p>🎖️ Veteran-owned businesses receive 50% off</p>
                    </div>
                </div>
            </body>
            </html>
            """

            email_service.send_email(
                to=EmailRecipient(email=request.email, name=request.name),
                subject="We received your message - ReconAI",
                html=auto_reply_html,
                tags=[{"name": "category", "value": "contact_auto_reply"}]
            )

        except Exception as e:
            print(f"Failed to send auto-reply email: {str(e)}")

        return ContactFormResponse(
            success=True,
            message="Thank you for contacting us! We'll get back to you within 24 hours.",
            ticket_id=submission_id
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to submit contact form: {str(e)}"
        )


@router.get("/submissions/{submission_id}")
async def get_submission(submission_id: str):
    """Get contact form submission by ID (for internal use)"""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            "SELECT * FROM contact_submissions WHERE id = ?",
            (submission_id,)
        )
        row = cursor.fetchone()

        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Submission not found"
            )

        return {
            "id": row["id"],
            "name": row["name"],
            "email": row["email"],
            "subject": row["subject"],
            "message": row["message"],
            "phone": row["phone"],
            "company": row["company"],
            "source": row["source"],
            "created_at": row["created_at"]
        }
