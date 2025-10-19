import os, pathlib
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

    # Support both PostgreSQL (DATABASE_URL) and SQLite (QVENTORY_DB_PATH)
    # PostgreSQL takes priority if both are set
    _database_url = os.environ.get("DATABASE_URL")
    _db_path = os.environ.get("QVENTORY_DB_PATH")

    if _database_url:
        # Use PostgreSQL or other database URL
        SQLALCHEMY_DATABASE_URI = _database_url
    elif _db_path:
        # Use SQLite with custom path
        p = pathlib.Path(_db_path)
        SQLALCHEMY_DATABASE_URI = f"sqlite:////{p.as_posix().lstrip('/')}"
    else:
        # Default to SQLite
        SQLALCHEMY_DATABASE_URI = "sqlite:////opt/qventory/data/app.db"
