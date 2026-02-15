from flask import Flask, request
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables before importing Config
env_path = Path(__file__).parent.parent / '.env'
if env_path.exists():
    load_dotenv(env_path)
else:
    # Try production path
    prod_env = Path('/opt/qventory/qventory/.env')
    if prod_env.exists():
        load_dotenv(prod_env)

from .config import Config
from .extensions import db, login_manager, migrate
from .routes import main_bp, auth_bp, auto_relist_bp
from .routes.reports import reports_bp
from .routes.ebay_auth import ebay_auth_bp
from .routes.expenses import expenses_bp
from .routes.receipts import receipts_bp
from .routes.webhooks import webhook_bp
from .routes.webhooks_platform import platform_webhook_bp
# DISABLED: Admin logging/webhooks consoles (reducing server load)
# from .routes.admin_webhooks import admin_webhooks_bp
# from .routes.admin_logs import admin_logs_bp
from .routes.tax_reports import tax_reports_bp

def _maybe_seed_demo():
    """
    Para desarrollo: export QVENTORY_SEED_DEMO=1 para crear un usuario demo
    con 3 ítems de ejemplo y settings asociados.
    """
    import os
    if os.environ.get("QVENTORY_SEED_DEMO") != "1":
        return

    from .models import User, Item
    from .helpers import (
        get_or_create_settings, generate_sku, compose_location_code
    )
    from .extensions import db

    if User.query.count() > 0:
        return

    demo = User(email="demo@example.com", username="demo")
    demo.set_password("demo123")  # solo dev
    db.session.add(demo)
    db.session.commit()

    s = get_or_create_settings(demo)

    examples = [
        ("Dell Latitude 7490", {"A": "1", "B": "2", "S": "1", "C": "1"}, "https://example.com/listing/7490"),
        ("Star Wars VHS Lot", {"A": "1", "B": "3", "S": "2", "C": "1"}, "https://example.com/listing/vhs"),
        ("Nintendo Wii Console", {"A": "2", "B": "1", "S": "1", "C": "2"}, "https://example.com/listing/wii"),
    ]
    for title, comp, link in examples:
        sku = generate_sku()
        loc = compose_location_code(
            A=comp.get("A"), B=comp.get("B"), S=comp.get("S"), C=comp.get("C"),
            enabled=tuple(s.enabled_levels())
        )
        it = Item(
            user_id=demo.id,
            title=title, sku=sku, listing_link=link,
            A=comp.get("A"), B=comp.get("B"), S=comp.get("S"), C=comp.get("C"),
            location_code=loc
        )
        db.session.add(it)
    db.session.commit()


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(ebay_auth_bp)
    app.register_blueprint(expenses_bp)
    app.register_blueprint(receipts_bp)
    app.register_blueprint(auto_relist_bp)
    app.register_blueprint(webhook_bp)
    app.register_blueprint(platform_webhook_bp)
    # DISABLED: Admin logging/webhooks consoles (reducing server load)
    # app.register_blueprint(admin_webhooks_bp)
    # app.register_blueprint(admin_logs_bp)
    app.register_blueprint(tax_reports_bp)

    # ==================== ACTIVITY TRACKING MIDDLEWARE ====================
    @app.before_request
    def update_user_activity():
        """
        Update last_activity timestamp for authenticated users

        This tracks ANY authenticated request (not just explicit logins).
        Used by polling system to determine if a user is "active" and should
        have their eBay inventory checked for new items.

        Throttled to 2-minute updates to reduce DB writes.
        """
        from flask_login import current_user
        from datetime import datetime, timedelta

        if current_user.is_authenticated:
            now = datetime.utcnow()

            # Throttle: only update if last_activity is None or older than 2 minutes
            # This reduces DB writes from every request to ~30 per hour max
            if not current_user.last_activity or (now - current_user.last_activity) > timedelta(minutes=2):
                try:
                    current_user.last_activity = now
                    db.session.commit()
                except Exception as e:
                    # Don't break the request if activity tracking fails
                    db.session.rollback()
                    print(f"[ACTIVITY_TRACKING] Error updating last_activity: {e}")

    # Register template filters
    @app.context_processor
    def inject_theme_preference():
        from flask_login import current_user
        theme = "dark"
        if current_user.is_authenticated:
            try:
                settings = current_user.settings
                if settings and settings.theme_preference:
                    theme = settings.theme_preference
            except Exception:
                theme = "dark"
        return {"theme_preference": theme}

    @app.context_processor
    def inject_support_counts():
        from flask_login import current_user
        support_unread_count = 0
        admin_support_unread_count = 0

        try:
            if current_user.is_authenticated and current_user.role in {"early_adopter", "premium", "plus", "pro", "god"}:
                from qventory.routes.main import _support_unread_for_user
                support_unread_count = _support_unread_for_user(current_user.id)
        except Exception:
            support_unread_count = 0

        try:
            from qventory.routes.main import check_admin_auth, _support_unread_for_admin
            if check_admin_auth():
                admin_support_unread_count = _support_unread_for_admin()
        except Exception:
            admin_support_unread_count = 0

        return {
            "support_unread_count": support_unread_count,
            "admin_support_unread_count": admin_support_unread_count,
        }

    @app.context_processor
    def inject_impersonation_state():
        from flask import session
        impersonating = bool(session.get("impersonating"))
        impersonated_user_id = session.get("impersonated_user_id")
        return {
            "impersonating": impersonating,
            "impersonated_user_id": impersonated_user_id,
        }

    @app.after_request
    def add_security_headers(response):
        # Basic security headers for SEO/security scanners
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-site")

        # HSTS: enable only when serving HTTPS
        if response.headers.get("Strict-Transport-Security") is None and request.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"

        # CSP: allow common inline styles/scripts used in templates; tighten later if needed
        if "Content-Security-Policy" not in response.headers:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "img-src 'self' data: https:; "
                "script-src 'self' https: 'unsafe-inline'; "
                "style-src 'self' https: 'unsafe-inline'; "
                "connect-src 'self' https:; "
                "font-src 'self' https: data:; "
                "frame-ancestors 'none'; "
                "base-uri 'self'; "
                "form-action 'self';"
            )

        # Cache static assets aggressively
        if request.path.startswith("/static/"):
            response.headers.setdefault("Cache-Control", "public, max-age=31536000, immutable")
        return response

    # Register template filters
    @app.template_filter('timeago')
    def timeago_filter(dt):
        """Convert datetime to relative time (e.g., '2h ago', '3d ago')"""
        if not dt:
            return '—'

        from datetime import datetime, timezone

        # Ensure dt is timezone-aware
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        diff = now - dt

        seconds = diff.total_seconds()

        if seconds < 60:
            return 'just now'
        elif seconds < 3600:
            minutes = int(seconds / 60)
            return f'{minutes}m ago' if minutes > 1 else '1m ago'
        elif seconds < 86400:
            hours = int(seconds / 3600)
            return f'{hours}h ago' if hours > 1 else '1h ago'
        elif seconds < 604800:
            days = int(seconds / 86400)
            return f'{days}d ago' if days > 1 else '1d ago'
        elif seconds < 2592000:
            weeks = int(seconds / 604800)
            return f'{weeks}w ago' if weeks > 1 else '1w ago'
        elif seconds < 31536000:
            months = int(seconds / 2592000)
            return f'{months}mo ago' if months > 1 else '1mo ago'
        else:
            years = int(seconds / 31536000)
            return f'{years}y ago' if years > 1 else '1y ago'

    # Register error handlers
    @app.errorhandler(404)
    def not_found_error(error):
        from flask import render_template
        return render_template('404.html'), 404

    @app.errorhandler(500)
    def internal_error(error):
        from flask import render_template
        db.session.rollback()
        return render_template('404.html'), 500

    with app.app_context():
        print("DB URI ->", app.config.get("SQLALCHEMY_DATABASE_URI"), flush=True)
        db.create_all()

        # Seed plan limits (always run to keep them updated)
        from qventory.helpers.seed_plans import seed_plan_limits
        seed_plan_limits()

        # Initialize AI token configs
        from qventory.models.ai_token import AITokenConfig
        AITokenConfig.initialize_defaults()

        _maybe_seed_demo()  # ahora sí existe

    return app
