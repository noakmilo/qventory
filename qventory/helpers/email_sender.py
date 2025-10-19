"""
Email sending helper for Qventory
Supports verification codes and password reset emails
"""
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import url_for


def send_email(to_email, subject, html_body, text_body=None):
    """
    Send an email using SMTP configuration from environment variables.

    Required environment variables:
    - SMTP_HOST: SMTP server hostname (e.g., smtp.gmail.com)
    - SMTP_PORT: SMTP server port (e.g., 587 for TLS, 465 for SSL)
    - SMTP_USER: SMTP username (email address)
    - SMTP_PASSWORD: SMTP password or app-specific password
    - SMTP_FROM_EMAIL: Email address to send from (defaults to SMTP_USER)
    - SMTP_FROM_NAME: Name to display as sender (defaults to "Qventory")

    Returns:
        (success: bool, error_message: str|None)
    """
    # Get SMTP configuration
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    from_email = os.environ.get("SMTP_FROM_EMAIL", smtp_user)
    from_name = os.environ.get("SMTP_FROM_NAME", "Qventory")

    # Validate configuration
    if not all([smtp_host, smtp_user, smtp_password]):
        return False, "Email not configured. Please contact support."

    try:
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f"{from_name} <{from_email}>"
        msg['To'] = to_email

        # Add text and HTML parts
        if text_body:
            part1 = MIMEText(text_body, 'plain')
            msg.attach(part1)

        part2 = MIMEText(html_body, 'html')
        msg.attach(part2)

        # Send email
        # Use SMTP_SSL for port 465, SMTP + starttls for ports 587/2525
        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
                server.login(smtp_user, smtp_password)
                server.sendmail(from_email, to_email, msg.as_string())
        else:
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_password)
                server.sendmail(from_email, to_email, msg.as_string())

        return True, None

    except smtplib.SMTPAuthenticationError:
        return False, "Email authentication failed. Please contact support."
    except smtplib.SMTPException as e:
        return False, f"Failed to send email: {str(e)}"
    except Exception as e:
        return False, f"Unexpected error sending email: {str(e)}"


def send_verification_email(to_email, code, username):
    """
    Send email verification code to user.

    Args:
        to_email: Recipient email address
        code: 6-digit verification code
        username: User's username

    Returns:
        (success: bool, error_message: str|None)
    """
    subject = "Verify your Qventory account"

    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 40px 20px; }}
            .header {{ text-align: center; margin-bottom: 30px; }}
            .logo {{ font-size: 24px; font-weight: bold; color: #2563eb; }}
            .code-box {{ background: #f3f4f6; border: 2px solid #e5e7eb; border-radius: 8px; padding: 24px; text-align: center; margin: 30px 0; }}
            .code {{ font-size: 36px; font-weight: bold; letter-spacing: 8px; color: #1f2937; font-family: 'Courier New', monospace; }}
            .content {{ line-height: 1.6; color: #374151; }}
            .footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #e5e7eb; font-size: 12px; color: #6b7280; text-align: center; }}
            .button {{ display: inline-block; background: #2563eb; color: white; padding: 12px 24px; border-radius: 6px; text-decoration: none; margin: 20px 0; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div class="logo">Qventory</div>
            </div>
            <div class="content">
                <h2>Welcome to Qventory, {username}!</h2>
                <p>Thanks for signing up. To complete your registration, please verify your email address using the code below:</p>

                <div class="code-box">
                    <div class="code">{code}</div>
                </div>

                <p><strong>This code will expire in 15 minutes.</strong></p>

                <p>If you didn't create a Qventory account, you can safely ignore this email.</p>

                <p>Need help? Contact us at support@qventory.com</p>
            </div>
            <div class="footer">
                <p>&copy; 2025 Qventory. All rights reserved.</p>
                <p>Inventory management made simple.</p>
            </div>
        </div>
    </body>
    </html>
    """

    text_body = f"""
Welcome to Qventory, {username}!

Your verification code is: {code}

This code will expire in 15 minutes.

If you didn't create a Qventory account, you can safely ignore this email.

Need help? Contact us at support@qventory.com

---
© 2025 Qventory. All rights reserved.
    """

    return send_email(to_email, subject, html_body, text_body)


def send_password_reset_email(to_email, code, username):
    """
    Send password reset code to user.

    Args:
        to_email: Recipient email address
        code: 6-digit reset code
        username: User's username

    Returns:
        (success: bool, error_message: str|None)
    """
    subject = "Reset your Qventory password"

    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 40px 20px; }}
            .header {{ text-align: center; margin-bottom: 30px; }}
            .logo {{ font-size: 24px; font-weight: bold; color: #2563eb; }}
            .code-box {{ background: #fef3c7; border: 2px solid #fbbf24; border-radius: 8px; padding: 24px; text-align: center; margin: 30px 0; }}
            .code {{ font-size: 36px; font-weight: bold; letter-spacing: 8px; color: #78350f; font-family: 'Courier New', monospace; }}
            .content {{ line-height: 1.6; color: #374151; }}
            .footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #e5e7eb; font-size: 12px; color: #6b7280; text-align: center; }}
            .warning {{ background: #fee2e2; border-left: 4px solid #dc2626; padding: 12px; margin: 20px 0; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div class="logo">Qventory</div>
            </div>
            <div class="content">
                <h2>Password Reset Request</h2>
                <p>Hi {username},</p>
                <p>We received a request to reset your Qventory password. Use the code below to reset your password:</p>

                <div class="code-box">
                    <div class="code">{code}</div>
                </div>

                <p><strong>This code will expire in 15 minutes.</strong></p>

                <div class="warning">
                    <strong>Security Notice:</strong> If you didn't request a password reset, please ignore this email and ensure your account is secure.
                </div>

                <p>Need help? Contact us at support@qventory.com</p>
            </div>
            <div class="footer">
                <p>&copy; 2025 Qventory. All rights reserved.</p>
                <p>Inventory management made simple.</p>
            </div>
        </div>
    </body>
    </html>
    """

    text_body = f"""
Password Reset Request

Hi {username},

We received a request to reset your Qventory password. Use the code below to reset your password:

{code}

This code will expire in 15 minutes.

SECURITY NOTICE: If you didn't request a password reset, please ignore this email and ensure your account is secure.

Need help? Contact us at support@qventory.com

---
© 2025 Qventory. All rights reserved.
    """

    return send_email(to_email, subject, html_body, text_body)
