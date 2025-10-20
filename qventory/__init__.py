from flask import Flask
from .config import Config
from .extensions import db, login_manager, migrate
from .routes import main_bp, auth_bp, auto_relist_bp
from .routes.reports import reports_bp
from .routes.ebay_auth import ebay_auth_bp
from .routes.expenses import expenses_bp
from .routes.webhooks import webhook_bp

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
    app.register_blueprint(auto_relist_bp)
    app.register_blueprint(webhook_bp)

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
