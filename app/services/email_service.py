# app/services/email_service.py

"""
Email Service - Resend Integration
Handles transactional emails for ReconAI
"""

import os
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, EmailStr

# Import Resend
try:
    import resend
    RESEND_AVAILABLE = True
except ImportError:
    RESEND_AVAILABLE = False
    print("Warning: resend package not installed. Email functionality disabled.")


class EmailRecipient(BaseModel):
    """Email recipient"""
    email: EmailStr
    name: Optional[str] = None


class EmailService:
    """Service for sending emails via Resend"""

    def __init__(self):
        self.api_key = os.getenv("RESEND_API_KEY", "")
        self.from_email = os.getenv("RESEND_FROM_EMAIL", "noreply@reconai.com")
        self.from_name = os.getenv("RESEND_FROM_NAME", "ReconAI")

        if RESEND_AVAILABLE and self.api_key:
            resend.api_key = self.api_key
            self.enabled = True
        else:
            self.enabled = False
            if not self.api_key:
                print("Warning: RESEND_API_KEY not configured. Email functionality disabled.")

    def send_email(
        self,
        to: List[EmailRecipient] | EmailRecipient | str,
        subject: str,
        html: str,
        text: Optional[str] = None,
        reply_to: Optional[str] = None,
        tags: Optional[List[Dict[str, str]]] = None
    ) -> Dict[str, Any]:
        """
        Send email via Resend

        Args:
            to: Recipient(s) - can be EmailRecipient, list of EmailRecipient, or email string
            subject: Email subject
            html: HTML email body
            text: Plain text email body (optional, auto-generated if not provided)
            reply_to: Reply-to email address
            tags: List of tags for tracking (e.g., [{"name": "category", "value": "welcome"}])

        Returns:
            Response from Resend API

        Raises:
            Exception if email sending fails
        """
        if not self.enabled:
            print(f"Email service disabled. Would send: {subject} to {to}")
            return {"status": "disabled", "message": "Email service not configured"}

        # Format recipients
        if isinstance(to, str):
            recipients = [to]
        elif isinstance(to, EmailRecipient):
            recipients = [to.email]
        elif isinstance(to, list):
            recipients = [r.email if isinstance(r, EmailRecipient) else r for r in to]
        else:
            recipients = [to]

        # Build email params
        params = {
            "from": f"{self.from_name} <{self.from_email}>",
            "to": recipients,
            "subject": subject,
            "html": html,
        }

        if text:
            params["text"] = text

        if reply_to:
            params["reply_to"] = reply_to

        if tags:
            params["tags"] = tags

        try:
            response = resend.Emails.send(params)
            return response
        except Exception as e:
            print(f"Error sending email: {str(e)}")
            raise

    # =========================================================================
    # TEMPLATE EMAILS
    # =========================================================================

    def send_welcome_email(
        self,
        to: EmailRecipient | str,
        user_name: str,
        organization_name: str,
        tier: str
    ) -> Dict[str, Any]:
        """Send welcome email to new user"""

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                .content {{ background: #f9fafb; padding: 30px; border-radius: 0 0 10px 10px; }}
                .button {{ display: inline-block; background: #667eea; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; margin: 20px 0; }}
                .footer {{ text-align: center; margin-top: 30px; color: #666; font-size: 14px; }}
                h1 {{ margin: 0; font-size: 28px; }}
                .badge {{ display: inline-block; background: #10b981; color: white; padding: 4px 12px; border-radius: 20px; font-size: 12px; text-transform: uppercase; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>Welcome to ReconAI! 🚀</h1>
                </div>
                <div class="content">
                    <p>Hi {user_name},</p>

                    <p>Welcome to <strong>{organization_name}</strong> on ReconAI!</p>

                    <p>Your account has been created with the <span class="badge">{tier}</span> plan, and you have access to:</p>

                    <ul>
                        <li>✅ AI-powered transaction classification</li>
                        <li>✅ DCAA-compliant expense tracking</li>
                        <li>✅ Professional bookkeeping tools</li>
                        <li>✅ Tax deduction analysis</li>
                        <li>✅ 14-day free trial</li>
                    </ul>

                    <p style="text-align: center;">
                        <a href="https://app.reconai.com/" class="button">Go to Dashboard</a>
                    </p>

                    <p><strong>Need help getting started?</strong></p>
                    <ul>
                        <li>📚 <a href="https://docs.reconai.com">Documentation</a></li>
                        <li>💬 <a href="https://support.reconai.com">Support Center</a></li>
                        <li>🎥 <a href="https://reconai.com/tutorials">Video Tutorials</a></li>
                    </ul>

                    <p>We're here to help! Reply to this email if you have any questions.</p>

                    <p>Best regards,<br>The ReconAI Team</p>
                </div>
                <div class="footer">
                    <p>ReconAI - Financial Intelligence for Veterans, Small Businesses & Enterprises</p>
                    <p>🎖️ Veteran-owned businesses receive 50% off all plans</p>
                </div>
            </div>
        </body>
        </html>
        """

        return self.send_email(
            to=to,
            subject=f"Welcome to ReconAI, {user_name}!",
            html=html,
            tags=[{"name": "category", "value": "welcome"}]
        )

    def send_team_invite_email(
        self,
        to: EmailRecipient | str,
        inviter_name: str,
        organization_name: str,
        role: str,
        invite_link: str
    ) -> Dict[str, Any]:
        """Send team invitation email"""

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                .content {{ background: #f9fafb; padding: 30px; border-radius: 0 0 10px 10px; }}
                .button {{ display: inline-block; background: #667eea; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; margin: 20px 0; }}
                .footer {{ text-align: center; margin-top: 30px; color: #666; font-size: 14px; }}
                h1 {{ margin: 0; font-size: 28px; }}
                .role {{ display: inline-block; background: #f59e0b; color: white; padding: 4px 12px; border-radius: 20px; font-size: 12px; text-transform: uppercase; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>You've Been Invited! 🎉</h1>
                </div>
                <div class="content">
                    <p><strong>{inviter_name}</strong> has invited you to join <strong>{organization_name}</strong> on ReconAI.</p>

                    <p>Your role: <span class="role">{role}</span></p>

                    <p>ReconAI is a powerful financial intelligence platform that helps businesses track expenses, manage bookkeeping, and stay compliant with DCAA regulations.</p>

                    <p style="text-align: center;">
                        <a href="{invite_link}" class="button">Accept Invitation</a>
                    </p>

                    <p style="color: #666; font-size: 14px;">This invitation link will expire in 7 days.</p>

                    <p>Questions? Reply to this email and we'll help you get started!</p>

                    <p>Best regards,<br>The ReconAI Team</p>
                </div>
                <div class="footer">
                    <p>ReconAI - Financial Intelligence Platform</p>
                </div>
            </div>
        </body>
        </html>
        """

        return self.send_email(
            to=to,
            subject=f"You've been invited to {organization_name} on ReconAI",
            html=html,
            tags=[{"name": "category", "value": "team_invite"}]
        )

    def send_trial_ending_email(
        self,
        to: EmailRecipient | str,
        user_name: str,
        organization_name: str,
        days_remaining: int,
        upgrade_link: str
    ) -> Dict[str, Any]:
        """Send trial ending reminder email"""

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                .content {{ background: #f9fafb; padding: 30px; border-radius: 0 0 10px 10px; }}
                .button {{ display: inline-block; background: #10b981; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; margin: 20px 0; }}
                .footer {{ text-align: center; margin-top: 30px; color: #666; font-size: 14px; }}
                h1 {{ margin: 0; font-size: 28px; }}
                .warning {{ background: #fef3c7; border-left: 4px solid #f59e0b; padding: 15px; margin: 20px 0; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>Your Trial is Ending Soon ⏰</h1>
                </div>
                <div class="content">
                    <p>Hi {user_name},</p>

                    <div class="warning">
                        <strong>Your free trial for {organization_name} ends in {days_remaining} days.</strong>
                    </div>

                    <p>We hope you've enjoyed using ReconAI! To continue accessing:</p>

                    <ul>
                        <li>✅ AI-powered transaction classification</li>
                        <li>✅ DCAA-compliant expense tracking</li>
                        <li>✅ Professional bookkeeping tools</li>
                        <li>✅ Tax deduction analysis</li>
                    </ul>

                    <p>Choose a plan that fits your needs:</p>

                    <p style="text-align: center;">
                        <a href="{upgrade_link}" class="button">Upgrade Now</a>
                    </p>

                    <p><strong>Special Offers:</strong></p>
                    <ul>
                        <li>🎖️ <strong>Veterans:</strong> 50% off all plans</li>
                        <li>💼 <strong>Annual billing:</strong> Save 2 months</li>
                    </ul>

                    <p>Have questions? We're here to help!</p>

                    <p>Best regards,<br>The ReconAI Team</p>
                </div>
                <div class="footer">
                    <p>ReconAI - Financial Intelligence Platform</p>
                </div>
            </div>
        </body>
        </html>
        """

        return self.send_email(
            to=to,
            subject=f"Your ReconAI trial ends in {days_remaining} days",
            html=html,
            tags=[{"name": "category", "value": "trial_ending"}]
        )

    def send_password_reset_email(
        self,
        to: EmailRecipient | str,
        user_name: str,
        reset_link: str
    ) -> Dict[str, Any]:
        """Send password reset email"""

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                .content {{ background: #f9fafb; padding: 30px; border-radius: 0 0 10px 10px; }}
                .button {{ display: inline-block; background: #667eea; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; margin: 20px 0; }}
                .footer {{ text-align: center; margin-top: 30px; color: #666; font-size: 14px; }}
                h1 {{ margin: 0; font-size: 28px; }}
                .warning {{ background: #fee2e2; border-left: 4px solid #ef4444; padding: 15px; margin: 20px 0; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>Reset Your Password 🔐</h1>
                </div>
                <div class="content">
                    <p>Hi {user_name},</p>

                    <p>We received a request to reset your ReconAI password.</p>

                    <p style="text-align: center;">
                        <a href="{reset_link}" class="button">Reset Password</a>
                    </p>

                    <p style="color: #666; font-size: 14px;">This link will expire in 1 hour for security reasons.</p>

                    <div class="warning">
                        <strong>Didn't request this?</strong><br>
                        If you didn't request a password reset, please ignore this email or contact support if you're concerned about your account security.
                    </div>

                    <p>Best regards,<br>The ReconAI Team</p>
                </div>
                <div class="footer">
                    <p>ReconAI - Financial Intelligence Platform</p>
                </div>
            </div>
        </body>
        </html>
        """

        return self.send_email(
            to=to,
            subject="Reset your ReconAI password",
            html=html,
            tags=[{"name": "category", "value": "password_reset"}]
        )

    def send_monthly_report_email(
        self,
        to: EmailRecipient | str,
        user_name: str,
        month: str,
        total_transactions: int,
        business_expenses: float,
        personal_expenses: float,
        report_link: str
    ) -> Dict[str, Any]:
        """Send monthly financial report email"""

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                .content {{ background: #f9fafb; padding: 30px; border-radius: 0 0 10px 10px; }}
                .button {{ display: inline-block; background: #667eea; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; margin: 20px 0; }}
                .footer {{ text-align: center; margin-top: 30px; color: #666; font-size: 14px; }}
                h1 {{ margin: 0; font-size: 28px; }}
                .stats {{ background: white; padding: 20px; border-radius: 8px; margin: 20px 0; }}
                .stat {{ display: inline-block; width: 45%; margin: 10px; text-align: center; }}
                .stat-value {{ font-size: 24px; font-weight: bold; color: #667eea; }}
                .stat-label {{ font-size: 14px; color: #666; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>Your {month} Report 📊</h1>
                </div>
                <div class="content">
                    <p>Hi {user_name},</p>

                    <p>Here's your financial summary for {month}:</p>

                    <div class="stats">
                        <div class="stat">
                            <div class="stat-value">{total_transactions}</div>
                            <div class="stat-label">Transactions</div>
                        </div>
                        <div class="stat">
                            <div class="stat-value">${business_expenses:,.2f}</div>
                            <div class="stat-label">Business Expenses</div>
                        </div>
                        <div class="stat">
                            <div class="stat-value">${personal_expenses:,.2f}</div>
                            <div class="stat-label">Personal Expenses</div>
                        </div>
                    </div>

                    <p style="text-align: center;">
                        <a href="{report_link}" class="button">View Full Report</a>
                    </p>

                    <p><strong>Next Steps:</strong></p>
                    <ul>
                        <li>📥 Download your report for tax purposes</li>
                        <li>✅ Review and categorize any uncertain transactions</li>
                        <li>📋 Export to QuickBooks or your accounting software</li>
                    </ul>

                    <p>Best regards,<br>The ReconAI Team</p>
                </div>
                <div class="footer">
                    <p>ReconAI - Financial Intelligence Platform</p>
                </div>
            </div>
        </body>
        </html>
        """

        return self.send_email(
            to=to,
            subject=f"Your ReconAI Report for {month}",
            html=html,
            tags=[{"name": "category", "value": "monthly_report"}]
        )


# Global email service instance
email_service = EmailService()
