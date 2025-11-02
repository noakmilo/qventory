import os
from datetime import timedelta

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SHIPPO_API_KEY = os.environ.get("SHIPPO_API_KEY")

    # Session configuration
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)  # Sessions last 30 days
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "False") == "True"  # True in production with HTTPS
    SESSION_COOKIE_HTTPONLY = True  # Prevent XSS attacks
    SESSION_COOKIE_SAMESITE = 'Lax'  # CSRF protection

    # Remember Me cookie configuration
    REMEMBER_COOKIE_DURATION = timedelta(days=30)  # Remember Me lasts 30 days
    REMEMBER_COOKIE_SECURE = os.environ.get("REMEMBER_COOKIE_SECURE", "False") == "True"  # True in production with HTTPS
    REMEMBER_COOKIE_HTTPONLY = True

    # Email/SMTP configuration (required for email verification and password reset)
    # Set these environment variables:
    # - SMTP_HOST: SMTP server (e.g., smtp.gmail.com)
    # - SMTP_PORT: Port (587 for TLS, 465 for SSL)
    # - SMTP_USER: Email username
    # - SMTP_PASSWORD: Email password or app-specific password
    # - SMTP_FROM_EMAIL: Sender email (optional, defaults to SMTP_USER)
    # - SMTP_FROM_NAME: Sender name (optional, defaults to "Qventory")

    # PostgreSQL Database URL (required)
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL")

    # SQLAlchemy Engine Options - optimize connection pooling and prevent idle transactions
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': 10,              # Max connections in pool per worker
        'pool_recycle': 3600,         # Recycle connections after 1 hour
        'pool_pre_ping': True,        # Verify connections before using (detect stale connections)
        'max_overflow': 5,            # Allow 5 extra connections beyond pool_size
        'pool_timeout': 30,           # Timeout waiting for connection from pool
    }
