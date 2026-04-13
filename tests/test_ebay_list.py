import os

from qventory.extensions import db
from qventory.helpers import ebay_inventory
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


def test_fetch_active_listings_snapshot_merges_image_urls(monkeypatch):
    def fake_fetch_offers(user_id, limit=200, offset=0):
        return {
            "success": True,
            "offers": [
                {
                    "ebay_listing_id": "123",
                    "ebay_sku": "SKU-1",
                    "product": {
                        "title": "Alpha",
                        "description": "Offer payload",
                        "imageUrls": [],
                    },
                    "item_price": 19.99,
                    "source": "offers_api",
                }
            ],
            "total": 1,
            "limit": limit,
            "offset": offset,
        }

    def fake_trading_api(user_id, max_items=1000, collect_failures=False, return_meta=False):
        items = [
            {
                "ebay_listing_id": "123",
                "ebay_sku": "SKU-1",
                "product": {
                    "title": "Alpha",
                    "description": "Trading payload",
                    "imageUrls": ["https://img.example/123.jpg"],
                },
                "item_price": 19.99,
                "source": "trading_api",
            }
        ]
        meta = {"is_complete": True, "rate_limited": False, "incomplete_reason": None}
        if return_meta:
            return items, meta
        if collect_failures:
            return items, []
        return items

    monkeypatch.setattr(ebay_inventory, "fetch_ebay_inventory_offers", fake_fetch_offers)
    monkeypatch.setattr(ebay_inventory, "get_active_listings_trading_api", fake_trading_api)

    result = ebay_inventory.fetch_active_listings_snapshot(42)

    assert result["success"] is True
    assert len(result["offers"]) == 1
    assert result["offers"][0]["product"]["imageUrls"] == ["https://img.example/123.jpg"]


def test_get_image_candidates_for_listing_scans_beyond_200_active_listings(monkeypatch):
    def fake_details(user_id, listing_id):
        return {}

    def fake_active_listings(user_id, max_items=1000, collect_failures=True):
        items = []
        for idx in range(300):
            items.append(
                {
                    "ebay_listing_id": str(idx),
                    "product": {"imageUrls": [f"https://img.example/{idx}.jpg"]},
                    "source": "trading_api",
                }
            )
        if collect_failures:
            return items[:max_items], []
        return items[:max_items]

    monkeypatch.setattr(ebay_inventory, "get_listing_details_trading_api", fake_details)
    monkeypatch.setattr(ebay_inventory, "get_active_listings_trading_api", fake_active_listings)

    candidates = ebay_inventory.get_image_candidates_for_listing(42, "250")

    assert candidates == ["https://img.example/250.jpg"]
