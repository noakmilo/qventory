from flask import Flask
from .config import Config
from .extensions import db, login_manager
from .routes import main_bp, auth_bp

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # init extensions
    db.init_app(app)
    login_manager.init_app(app)

    # blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)

    # crea tablas
    with app.app_context():
        db.create_all()
        # Seed opcional controlado por env var (solo DEV)
        _maybe_seed_demo()

    return app


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

    # si ya hay usuarios, no hacer nada
    if User.query.count() > 0:
        return

    # crea usuario demo
    demo = User(email="demo@example.com", username="demo")
    demo.set_password("demo123")  # solo dev
    db.session.add(demo)
    db.session.commit()

    # settings del demo
    s = get_or_create_settings(demo)

    # ítems de ejemplo
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
