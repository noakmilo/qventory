import os

from qventory.extensions import db
from qventory.models.user import User
from qventory.models.ebay_listing_draft import EbayListingDraft
from qventory.routes.permissions import require_role, require_feature_flag
from qventory.routes.ebay_list import _validate_draft


def _make_app():
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"
    os.environ["FEATURE_EBAY_LISTING_CREATE_ENABLED"] = "True"
    from qventory import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.app_context():
        db.create_all()
    return app


def test_require_role_blocks_non_god():
    app = _make_app()
    with app.app_context():
        user = User(email="free@example.com", username="freeuser")
        user.set_password("test")
        user.role = "free"
        db.session.add(user)
        db.session.commit()

    @require_feature_flag("FEATURE_EBAY_LISTING_CREATE_ENABLED")
    @require_role("god")
    def protected():
        return "ok"

    with app.test_request_context("/api/ebay/drafts"):
        from flask_login import login_user
        user = User.query.filter_by(username="freeuser").first()
        login_user(user)
        resp = protected()
        assert resp.status_code == 403


def test_draft_validation_missing_fields():
    draft = EbayListingDraft(
        title="",
        description_text="",
        description_html="",
        currency="USD"
    )
    errors = _validate_draft(draft)
    assert "title" in errors
    assert "description" in errors
    assert "sku" in errors
    assert "quantity" in errors
    assert "price" in errors
