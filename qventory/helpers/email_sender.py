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


def send_plan_limit_reached_email(to_email, username, max_items):
    subject = "You have reached your Qventory plan limit"
    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 36px 20px; }}
            .header {{ text-align: center; margin-bottom: 24px; }}
            .logo {{ font-size: 24px; font-weight: bold; color: #2563eb; }}
            .content {{ line-height: 1.6; color: #374151; }}
            .highlight {{ background: #fff7ed; border: 1px solid #fed7aa; padding: 12px 14px; border-radius: 8px; }}
            .button {{ display: inline-block; background: #2563eb; color: white; padding: 10px 18px; border-radius: 6px; text-decoration: none; margin: 18px 0; }}
            .footer {{ margin-top: 32px; padding-top: 16px; border-top: 1px solid #e5e7eb; font-size: 12px; color: #6b7280; text-align: center; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div class="logo">Qventory</div>
            </div>
            <div class="content">
                <h2>Hi {username},</h2>
                <p>You've reached the limit of your current plan. Right now your plan allows up to <strong>{max_items}</strong> active items.</p>
                <div class="highlight">
                    Upgrade to unlock higher item limits and keep your inventory fully synced.
                </div>
                <a class="button" href="https://qventory.com/upgrade">Upgrade your plan</a>
                <p>If you believe this is a mistake, reply to this email and we'll help you.</p>
            </div>
            <div class="footer">
                <p>&copy; 2025 Qventory. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """
    text_body = f"""
Hi {username},

You've reached the limit of your current plan. Your plan allows up to {max_items} active items.

Upgrade to unlock higher item limits and keep your inventory fully synced:
https://qventory.com/upgrade

If you believe this is a mistake, reply to this email and we'll help you.

---
© 2025 Qventory. All rights reserved.
    """
    return send_email(to_email, subject, html_body, text_body)


def send_welcome_verified_email(to_email, username):
    subject = "Welcome to Qventory"
    discord_url = "https://discord.gg/KWGCZDGWMN"
    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 36px 20px; }}
            .header {{ text-align: center; margin-bottom: 24px; }}
            .logo {{ font-size: 24px; font-weight: bold; color: #2563eb; }}
            .content {{ line-height: 1.6; color: #374151; }}
            .button {{ display: inline-block; background: #2563eb; color: white; padding: 10px 18px; border-radius: 6px; text-decoration: none; margin: 12px 0; }}
            .button-secondary {{ display: inline-block; background: #111827; color: white; padding: 10px 18px; border-radius: 6px; text-decoration: none; margin: 12px 0; }}
            .footer {{ margin-top: 32px; padding-top: 16px; border-top: 1px solid #e5e7eb; font-size: 12px; color: #6b7280; text-align: center; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div class="logo">Qventory</div>
            </div>
            <div class="content">
                <h2>Welcome, {username}!</h2>
                <p>Your account is verified and ready to go. Start organizing, pricing, and tracking your inventory with Qventory.</p>
                <p>Join our community to get fast answers and tips:</p>
                <a class="button-secondary" href="{discord_url}">Join the Discord</a>
                <p>Want more power from day one?</p>
                <ul>
                    <li>Higher active item limits</li>
                    <li>Advanced analytics</li>
                    <li>AI research tokens</li>
                    <li>Bulk actions to save time</li>
                </ul>
                <a class="button" href="https://qventory.com/upgrade">Upgrade your plan</a>
            </div>
            <div class="footer">
                <p>&copy; 2025 Qventory. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """
    text_body = f"""
Welcome, {username}!

Your account is verified and ready to go.
Join the Discord community: {discord_url}

Upgrade to unlock higher limits, advanced analytics, AI research tokens, and bulk actions:
https://qventory.com/upgrade

---
© 2025 Qventory. All rights reserved.
    """
    return send_email(to_email, subject, html_body, text_body)


def send_plan_upgrade_email(to_email, username, plan_name):
    plan_title = plan_name.replace("_", " ").title()
    subject = f"Welcome to {plan_title}"
    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 36px 20px; }}
            .header {{ text-align: center; margin-bottom: 24px; }}
            .logo {{ font-size: 24px; font-weight: bold; color: #2563eb; }}
            .content {{ line-height: 1.6; color: #374151; }}
            .highlight {{ background: #eff6ff; border: 1px solid #bfdbfe; padding: 12px 14px; border-radius: 8px; }}
            .footer {{ margin-top: 32px; padding-top: 16px; border-top: 1px solid #e5e7eb; font-size: 12px; color: #6b7280; text-align: center; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div class="logo">Qventory</div>
            </div>
            <div class="content">
                <h2>You're on {plan_title} 🎉</h2>
                <p>Thanks for upgrading, {username}. Your plan unlocks:</p>
                <div class="highlight">
                    <ul>
                        <li>Higher active item limits</li>
                        <li>Advanced analytics and reporting</li>
                        <li>AI research tokens for better pricing</li>
                        <li>Bulk workflows to save hours</li>
                    </ul>
                </div>
                <p>If you need help getting the most out of your plan, just reply to this email.</p>
            </div>
            <div class="footer">
                <p>&copy; 2025 Qventory. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """
    text_body = f"""
You're on {plan_title}!

Thanks for upgrading, {username}. Your plan unlocks higher item limits, advanced analytics, AI research tokens, and bulk workflows.

If you need help getting the most out of your plan, just reply to this email.

---
© 2025 Qventory. All rights reserved.
    """
    return send_email(to_email, subject, html_body, text_body)


def send_plan_cancellation_email(to_email, username):
    subject = "Your Qventory plan has been cancelled"
    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 36px 20px; }}
            .header {{ text-align: center; margin-bottom: 24px; }}
            .logo {{ font-size: 24px; font-weight: bold; color: #2563eb; }}
            .content {{ line-height: 1.6; color: #374151; }}
            .button {{ display: inline-block; background: #2563eb; color: white; padding: 10px 18px; border-radius: 6px; text-decoration: none; margin: 12px 0; }}
            .footer {{ margin-top: 32px; padding-top: 16px; border-top: 1px solid #e5e7eb; font-size: 12px; color: #6b7280; text-align: center; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div class="logo">Qventory</div>
            </div>
            <div class="content">
                <h2>Subscription cancelled</h2>
                <p>Hi {username}, your subscription has been cancelled. You're always welcome back.</p>
                <p>If you want to return, you can upgrade anytime:</p>
                <a class="button" href="https://qventory.com/upgrade">View plans</a>
            </div>
            <div class="footer">
                <p>&copy; 2025 Qventory. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """
    text_body = f"""
Subscription cancelled

Hi {username}, your subscription has been cancelled. You're always welcome back.
Upgrade anytime: https://qventory.com/upgrade

---
© 2025 Qventory. All rights reserved.
    """
    return send_email(to_email, subject, html_body, text_body)


def send_payment_failed_email(to_email, username):
    subject = "Your Qventory payment failed"
    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 36px 20px; }}
            .header {{ text-align: center; margin-bottom: 24px; }}
            .logo {{ font-size: 24px; font-weight: bold; color: #2563eb; }}
            .content {{ line-height: 1.6; color: #374151; }}
            .highlight {{ background: #fef2f2; border: 1px solid #fecaca; padding: 12px 14px; border-radius: 8px; }}
            .button {{ display: inline-block; background: #2563eb; color: white; padding: 10px 18px; border-radius: 6px; text-decoration: none; margin: 12px 0; }}
            .footer {{ margin-top: 32px; padding-top: 16px; border-top: 1px solid #e5e7eb; font-size: 12px; color: #6b7280; text-align: center; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div class="logo">Qventory</div>
            </div>
            <div class="content">
                <h2>Your payment failed</h2>
                <p>Hi {username},</p>
                <div class="highlight">
                    <p>We couldn't process your payment after the trial period. To restore your plan privileges, please upgrade again.</p>
                </div>
                <p>No data is lost. All items and associated information remain intact and will be restored once payment is completed.</p>
                <a class="button" href="https://qventory.com/upgrade">Upgrade Now</a>
            </div>
            <div class="footer">
                <p>&copy; 2025 Qventory. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """
    text_body = f"""
Your payment failed

Hi {username},
We couldn't process your payment after the trial period. To restore your plan privileges, please upgrade again.

No data is lost. All items and associated information remain intact and will be restored once payment is completed.

Upgrade: https://qventory.com/upgrade

---
© 2025 Qventory. All rights reserved.
    """
    return send_email(to_email, subject, html_body, text_body)


def send_support_broadcast_email(to_email, username, subject, body, ticket_url):
    email_subject = f"Qventory Announcement: {subject}"
    safe_name = username or "there"
    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 36px 20px; }}
            .header {{ text-align: center; margin-bottom: 24px; }}
            .logo {{ font-size: 24px; font-weight: bold; color: #2563eb; }}
            .content {{ line-height: 1.6; color: #374151; }}
            .message {{ white-space: pre-wrap; background: #f8fafc; border: 1px solid #e5e7eb; padding: 14px 16px; border-radius: 10px; }}
            .button {{ display: inline-block; background: #2563eb; color: white; padding: 10px 18px; border-radius: 6px; text-decoration: none; margin: 16px 0; }}
            .footer {{ margin-top: 32px; padding-top: 16px; border-top: 1px solid #e5e7eb; font-size: 12px; color: #6b7280; text-align: center; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div class="logo">Qventory</div>
            </div>
            <div class="content">
                <h2>Hi {safe_name},</h2>
                <p>You have a new announcement from Qventory:</p>
                <div class="message">{body}</div>
                <a class="button" href="{ticket_url}">View Announcement</a>
                <p>Need help? Contact us at support@qventory.com</p>
            </div>
            <div class="footer">
                <p>&copy; 2025 Qventory. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """
    text_body = f"""
Hi {safe_name},

You have a new announcement from Qventory:

{body}

View it here: {ticket_url}

Need help? Contact us at support@qventory.com

---
© 2025 Qventory. All rights reserved.
    """
    return send_email(to_email, email_subject, html_body, text_body)


def send_pickup_scheduled_email(to_email, buyer_name, seller_name, pickup_date, pickup_time, address, details_url, calendar_url):
    subject = f"Pickup scheduled with {seller_name}"

    address_block = f"<p><strong>Pickup address:</strong> {address}</p>" if address else ""
    calendar_block = f'<a class="button" href="{calendar_url}">Add to calendar</a>' if calendar_url else ""

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
            .content {{ line-height: 1.6; color: #374151; }}
            .card {{ background: #f3f4f6; border-radius: 10px; padding: 16px; margin: 20px 0; }}
            .button {{ display: inline-block; background: #2563eb; color: white; padding: 12px 24px; border-radius: 6px; text-decoration: none; margin-top: 12px; }}
            .footer {{ margin-top: 30px; font-size: 12px; color: #6b7280; text-align: center; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div class="logo">Qventory</div>
            </div>
            <div class="content">
                <h2>Pickup scheduled</h2>
                <p>Hi {buyer_name}, your pickup with <strong>{seller_name}</strong> is confirmed.</p>
                <div class="card">
                    <p><strong>Date:</strong> {pickup_date}</p>
                    <p><strong>Time:</strong> {pickup_time}</p>
                    {address_block}
                </div>
                <a class="button" href="{details_url}">View appointment details</a>
                {calendar_block}
                <p>If you need to message the seller, use the appointment link above.</p>
            </div>
            <div class="footer">
                <p>&copy; 2025 Qventory. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """

    text_body = f"""
Pickup scheduled

Hi {buyer_name}, your pickup with {seller_name} is confirmed.

Date: {pickup_date}
Time: {pickup_time}
{f'Address: {address}' if address else ''}

View details: {details_url}
{f'Add to calendar: {calendar_url}' if calendar_url else ''}

---
© 2025 Qventory. All rights reserved.
    """

    return send_email(to_email, subject, html_body, text_body)


def send_pickup_message_email(to_email, sender_label, message, reply_url):
    subject = f"New pickup message from {sender_label}"

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
            .message {{ background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; }}
            .button {{ display: inline-block; background: #2563eb; color: white; padding: 12px 24px; border-radius: 6px; text-decoration: none; margin-top: 16px; }}
            .footer {{ margin-top: 30px; font-size: 12px; color: #6b7280; text-align: center; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div class="logo">Qventory</div>
            </div>
            <h2>New pickup message</h2>
            <p><strong>{sender_label}</strong> sent you a message:</p>
            <div class="message">{message}</div>
            <a class="button" href="{reply_url}">Reply to message</a>
            <div class="footer">
                <p>&copy; 2025 Qventory. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """

    text_body = f"""
New pickup message from {sender_label}

{message}

Reply: {reply_url}

---
© 2026 Qventory. All rights reserved.
    """

    return send_email(to_email, subject, html_body, text_body)
