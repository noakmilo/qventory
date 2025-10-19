# Email Verification - Quick Start

## 1. Configure SMTP in .env.local

Add these lines to your `.env.local` file:

```bash
# Email Configuration (Gmail example)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password
```

### Getting Gmail App Password:
1. Enable 2FA: https://myaccount.google.com/security
2. Generate App Password: https://myaccount.google.com/apppasswords
3. Copy the 16-character password

## 2. Run Migration

```bash
flask db upgrade
```

## 3. Restart Application

```bash
# Development
flask run

# Production
systemctl restart qventory
```

## 4. Test

1. Create new account at `/register`
2. Check email for 6-digit code
3. Verify email
4. Done! 🎉

## Features

- ✅ Email verification on registration
- ✅ Password reset via email
- ✅ Rate limiting (max 5 resends, 60s cooldown)
- ✅ Codes expire in 15 minutes
- ✅ "Remember me" functionality (30 days)

## Troubleshooting

**Email not sending?**
- Check SMTP credentials in `.env.local`
- Make sure you're using Gmail App Password, not regular password
- Check spam folder

**"Email not configured" error?**
- Make sure all SMTP_* variables are set in `.env.local`
- Restart your application

See [EMAIL_SETUP.md](EMAIL_SETUP.md) for detailed documentation.
