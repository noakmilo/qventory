# Email Verification Setup Guide

Qventory now includes email verification for user registration and password reset functionality. This guide will help you configure the email system.

## Features

- **Email Verification**: Users must verify their email address after registration using a 6-digit code
- **Password Reset**: Users can reset their password via email using a 6-digit code
- **Rate Limiting**: Prevents abuse with cooldown periods and maximum resend limits
- **Code Expiration**: Verification codes expire after 15 minutes for security
- **Resend Functionality**: Users can request new codes if they didn't receive them

## Configuration

### Step 1: Copy the example file

```bash
# For local development
cp .env.example .env.local

# For production
cp .env.example .env
```

### Step 2: Add SMTP credentials to your .env file

Edit your `.env.local` (development) or `.env` (production) and add:

```bash
# Email / SMTP Configuration
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_FROM_EMAIL=noreply@qventory.com  # Optional
SMTP_FROM_NAME=Qventory               # Optional

# Security (set to True in production with HTTPS)
SESSION_COOKIE_SECURE=False  # True in production
REMEMBER_COOKIE_SECURE=False # True in production
```

**Important**: Never commit `.env` or `.env.local` files to git - they're already in `.gitignore`.

## Email Provider Setup Examples

### Gmail (Good for testing/small deployments)

1. **Enable 2-Factor Authentication** on your Google account
2. **Generate an App Password**:
   - Go to https://myaccount.google.com/apppasswords
   - Select "Mail" and "Other (Custom name)"
   - Name it "Qventory" and click Generate
   - Copy the 16-character password

3. **Add to .env.local**:
```bash
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-16-char-app-password
```

### SendGrid (Recommended for production)

1. **Create a SendGrid account** at https://sendgrid.com
2. **Generate an API Key**:
   - Go to Settings > API Keys
   - Click "Create API Key"
   - Select "Full Access" and create

3. **Add to .env**:
```bash
SMTP_HOST=smtp.sendgrid.net
SMTP_PORT=587
SMTP_USER=apikey
SMTP_PASSWORD=your-sendgrid-api-key
SMTP_FROM_EMAIL=verified@yourdomain.com  # Must be verified in SendGrid
```

### AWS SES (Good for high volume)

1. **Verify your domain or email** in AWS SES console
2. **Create SMTP credentials** in SES > SMTP Settings

3. **Add to .env**:
```bash
SMTP_HOST=email-smtp.us-east-1.amazonaws.com
SMTP_PORT=587
SMTP_USER=your-aws-smtp-username
SMTP_PASSWORD=your-aws-smtp-password
SMTP_FROM_EMAIL=verified@yourdomain.com
```

### Mailgun

1. **Create a Mailgun account** at https://mailgun.com
2. **Verify your domain** in the Mailgun dashboard
3. **Get SMTP credentials** from Sending > Domain Settings > SMTP credentials

4. **Add to .env**:
```bash
SMTP_HOST=smtp.mailgun.org
SMTP_PORT=587
SMTP_USER=postmaster@your-domain.mailgun.org
SMTP_PASSWORD=your-mailgun-smtp-password
```

## Database Migration

Run the migration to add email verification tables:

```bash
# Development
flask db upgrade

# Production
sudo -u postgres psql qventory_db < migrations/versions/013_add_email_verification.py
# OR
flask db upgrade
```

The migration will:
- Add `email_verified` column to `users` table
- Create `email_verifications` table for storing verification codes

## Testing Email Configuration

### Test in Python Console

```python
from qventory.helpers.email_sender import send_verification_email

# Test sending a verification email
success, error = send_verification_email(
    to_email="test@example.com",
    code="123456",
    username="testuser"
)

if success:
    print("Email sent successfully!")
else:
    print(f"Error: {error}")
```

### Check Logs

Email sending errors will appear in your application logs:
```bash
# Check Gunicorn logs
tail -f /var/log/qventory/error.log

# Check systemd logs
journalctl -u qventory -f
```

## User Flow

### Registration Flow
1. User fills out registration form
2. Account is created with `email_verified = False`
3. 6-digit code is generated and sent via email
4. User enters code on verification page
5. Upon successful verification, `email_verified = True`
6. User is auto-logged in and redirected to dashboard

### Login Flow
1. User enters email and password
2. If credentials are correct but email is not verified:
   - User is redirected to verification page
   - Can request new code if needed
3. If email is verified, user is logged in

### Password Reset Flow
1. User clicks "Forgot password?" on login page
2. Enters their email address
3. 6-digit reset code is sent via email
4. User enters code and new password
5. Password is updated, user can log in with new password

## Rate Limiting

To prevent abuse, the system includes:

- **Cooldown Period**: 60 seconds between resend requests
- **Maximum Resends**: 5 resend attempts per verification code
- **Code Expiration**: All codes expire after 15 minutes
- **Failed Attempts**: Maximum 5 failed verification attempts per code

## Security Features

- **Code Expiration**: 15-minute lifetime for all codes
- **One-Time Use**: Codes can only be used once
- **Cryptographically Random**: Codes generated using `secrets` module
- **Email Enumeration Protection**: Generic messages don't reveal if email exists
- **Database Cleanup**: Old codes are automatically cleaned up (implement cleanup task)

## Troubleshooting

### "Email not configured" Error

**Problem**: SMTP environment variables are not set in your `.env` file.

**Solution**:
1. Make sure you have `.env.local` (development) or `.env` (production) file
2. Verify SMTP variables are set in the file:
```bash
# Check your .env.local file
grep SMTP .env.local

# Should show:
# SMTP_HOST=smtp.gmail.com
# SMTP_PORT=587
# SMTP_USER=your-email@gmail.com
# SMTP_PASSWORD=your-app-password
```
3. Restart your application to load new environment variables

### "Email authentication failed" Error

**Problem**: Invalid SMTP credentials.

**Solution**:
- For Gmail: Make sure you're using an **App Password**, not your regular password
- For other providers: Verify your SMTP username and password are correct
- Check that 2FA is enabled if required by your provider

### Emails Not Being Received

**Possible causes**:
1. **Spam Folder**: Check user's spam/junk folder
2. **Email Deliverability**: Verify your sending domain (for production use)
3. **Rate Limits**: Some providers have hourly/daily sending limits
4. **Blocked IP**: Check if your server IP is blacklisted

**Solutions**:
- Use a dedicated email service (SendGrid, AWS SES, Mailgun) for production
- Configure SPF, DKIM, and DMARC records for your domain
- Start with verified email addresses during testing

### Code Expiration Issues

**Problem**: Users complain codes expire too quickly.

**Solution**: Increase expiration time in `EmailVerification.__init__()`:
```python
def __init__(self, user_id, email, purpose='registration', expiry_minutes=30):  # Changed from 15 to 30
```

## Production Recommendations

1. **Use a dedicated email service** (SendGrid, AWS SES, Mailgun) instead of Gmail
2. **Set up SPF, DKIM, DMARC** records for your domain
3. **Use a verified sending domain** for better deliverability
4. **Enable HTTPS** and set secure cookie flags in your `.env`:
   ```bash
   SESSION_COOKIE_SECURE=True
   REMEMBER_COOKIE_SECURE=True
   ```
5. **Monitor email sending** with your provider's dashboard
6. **Set up email templates** in your provider's dashboard for better tracking

## Optional: Cleanup Task

Add this to your Celery tasks to clean up old verification codes:

```python
from celery import Celery
from qventory.models.email_verification import EmailVerification

@celery.task
def cleanup_expired_verifications():
    """Remove expired verification codes older than 24 hours"""
    EmailVerification.cleanup_expired()
```

Schedule it to run daily:
```python
# In your Celery config
beat_schedule = {
    'cleanup-verifications': {
        'task': 'qventory.tasks.cleanup_expired_verifications',
        'schedule': crontab(hour=3, minute=0),  # Run at 3 AM daily
    }
}
```

## Support

If you encounter issues:
1. Check application logs for detailed error messages
2. Verify all environment variables are set correctly
3. Test email configuration using the Python console test
4. Review your email provider's documentation
5. Check for IP blacklisting or rate limits

For production deployments, consider using a transactional email service with high deliverability rates and detailed analytics.
