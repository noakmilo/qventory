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

    @app.before_request
    def capture_referral_visit():
        """
        Capture UTM source visits for ref link analytics and signup attribution.
        Stores UTM params in session and logs a referral visit row.
        """
        from datetime import datetime
        from flask import request, session
        import hashlib
        import uuid
        from qventory.models.referral import ReferralVisit

        if request.method != "GET":
            return
        if request.path.startswith("/static"):
            return

        utm_source = (request.args.get("utm_source") or "").strip() or None
        if not utm_source:
            return

        session.setdefault("ref_session_id", uuid.uuid4().hex)
        session["ref_source"] = utm_source
        session["ref_medium"] = (request.args.get("utm_medium") or "").strip() or None
        session["ref_campaign"] = (request.args.get("utm_campaign") or "").strip() or None
        session["ref_content"] = (request.args.get("utm_content") or "").strip() or None
        session["ref_term"] = (request.args.get("utm_term") or "").strip() or None
        session["ref_landing_path"] = request.path
        session["ref_first_touch_at"] = datetime.utcnow().isoformat()

        ip = request.headers.get("X-Forwarded-For", request.remote_addr) or ""
        ip_hash = hashlib.sha256(ip.encode("utf-8")).hexdigest() if ip else None
        user_agent = (request.headers.get("User-Agent") or "")[:255]

        try:
            visit = ReferralVisit(
                utm_source=utm_source,
                utm_medium=session.get("ref_medium"),
                utm_campaign=session.get("ref_campaign"),
                utm_content=session.get("ref_content"),
                utm_term=session.get("ref_term"),
                landing_path=session.get("ref_landing_path"),
                session_id=session.get("ref_session_id"),
                ip_hash=ip_hash,
                user_agent=user_agent
            )
            db.session.add(visit)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"[REF_TRACKING] Error recording referral visit: {e}")

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

    @app.context_processor
    def inject_slow_movers_count():
        from flask_login import current_user
        from datetime import date, timedelta
        from qventory.helpers.inventory_queries import count_slow_movers
        from qventory.helpers.utils import get_or_create_settings

        count = 0
        try:
            if current_user.is_authenticated:
                s = current_user.settings or get_or_create_settings(current_user)
                if s and s.slow_movers_enabled:
                    days = int(s.slow_movers_days or 30)
                    days = max(1, min(days, 3650))
                    mode = (s.slow_movers_start_mode or "item_added").strip().lower()
                    today = date.today()
                    threshold_date = None
                    start_ready = True
                    if mode == "item_added":
                        threshold_date = today - timedelta(days=days)
                    elif mode in {"rule_created", "scheduled"}:
                        start_date = s.slow_movers_start_date or today
                        ready_date = start_date + timedelta(days=days)
                        if today < ready_date:
                            start_ready = False
                    else:
                        mode = "item_added"
                        threshold_date = today - timedelta(days=days)
                    count = count_slow_movers(
                        db.session,
                        user_id=current_user.id,
                        start_mode=mode,
                        threshold_date=threshold_date,
                        start_ready=start_ready,
                    )
        except Exception:
            count = 0

        return {"slow_movers_count": count}

    @app.context_processor
    def inject_feedback_unread_count():
        from flask_login import current_user
        from qventory.helpers.feedback_queries import count_unread_feedback
        from qventory.helpers.utils import get_or_create_settings

        count = 0
        try:
            if current_user.is_authenticated:
                s = current_user.settings or get_or_create_settings(current_user)
                if s and s.feedback_manager_enabled:
                    count = count_unread_feedback(
                        db.session,
                        user_id=current_user.id,
                        since_dt=s.feedback_last_viewed_at
                    )
        except Exception:
            count = 0

        return {"feedback_unread_count": count}

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
        # Do not print DB URI to logs (sensitive)
        db.create_all()

        # Seed plan limits (always run to keep them updated)
        from qventory.helpers.seed_plans import seed_plan_limits
        seed_plan_limits()

        # Initialize AI token configs (skip during migrations if schema is mid-change)
        if os.environ.get("SKIP_AI_TOKEN_SEED", "0") != "1":
            from qventory.models.ai_token import AITokenConfig
            AITokenConfig.initialize_defaults()

        _maybe_seed_demo()  # ahora sí existe

    return app
