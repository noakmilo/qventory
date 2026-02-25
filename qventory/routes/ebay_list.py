from datetime import datetime
import bleach
from flask import Blueprint, jsonify, request, render_template
from flask_login import login_required, current_user
from ..extensions import db
from ..models.ebay_listing_draft import EbayListingDraft
from ..models.ebay_category import EbayCategory
from ..routes.permissions import require_plan_feature, require_feature_flag
from ..helpers.ebay_specifics_cache import get_category_specifics
from ..helpers.ebay_image_upload import create_ebay_upload_session
from ..helpers.ebay_listing_publish import (
    create_or_replace_inventory_item,
    create_offer,
    publish_offer,
)
from ..helpers.ebay_account import get_account_policies, get_merchant_locations
from ..models.marketplace_credential import MarketplaceCredential


ebay_list_bp = Blueprint("ebay_list", __name__)

_rate_limits = {}


def _rate_limit(key: str, limit: int, window_seconds: int) -> bool:
    now = datetime.utcnow().timestamp()
    bucket = _rate_limits.get(key, [])
    bucket = [t for t in bucket if now - t < window_seconds]
    if len(bucket) >= limit:
        _rate_limits[key] = bucket
        return False
    bucket.append(now)
    _rate_limits[key] = bucket
    return True

ALLOWED_DESCRIPTION_TAGS = [
    "p", "br", "strong", "em", "ul", "ol", "li", "b", "i", "u",
    "h1", "h2", "h3", "h4", "blockquote", "span"
]
ALLOWED_DESCRIPTION_ATTRS = {"span": ["style"]}


def _sanitize_html(html: str | None) -> str | None:
    if not html:
        return None
    cleaned = bleach.clean(
        html,
        tags=ALLOWED_DESCRIPTION_TAGS,
        attributes=ALLOWED_DESCRIPTION_ATTRS,
        strip=True
    )
    return cleaned


def _draft_or_404(draft_id: int):
    draft = EbayListingDraft.query.get(draft_id)
    if not draft or draft.user_id != current_user.id:
        return None
    return draft


def _draft_images(draft: EbayListingDraft):
    return draft.images_json or []


def _validate_draft(draft: EbayListingDraft):
    errors = {}
    if not draft.title:
        errors["title"] = "Title is required."
    elif len(draft.title) > 80:
        errors["title"] = "Title must be 80 characters or fewer."

    if not draft.description_html_sanitized:
        errors["description"] = "Description is required."

    if not draft.category_id:
        errors["category_id"] = "Category is required."

    if not draft.condition_id:
        errors["condition_id"] = "Condition is required."

    if not draft.sku:
        errors["sku"] = "SKU is required."

    if not draft.quantity or draft.quantity <= 0:
        errors["quantity"] = "Quantity must be at least 1."

    if draft.price is None or float(draft.price) <= 0:
        errors["price"] = "Price must be greater than 0."

    if not draft.currency:
        errors["currency"] = "Currency is required."

    if not draft.fulfillment_policy_id:
        errors["fulfillment_policy_id"] = "Fulfillment policy ID is required."
    if not draft.payment_policy_id:
        errors["payment_policy_id"] = "Payment policy ID is required."
    if not draft.return_policy_id:
        errors["return_policy_id"] = "Return policy ID is required."

    images = _draft_images(draft)
    if not images:
        errors["images"] = "At least one image is required."
    else:
        has_ref = any(img.get("ebay_image_url") for img in images)
        if not has_ref:
            errors["images"] = "Images must be uploaded to eBay."

    if draft.category_id:
        try:
            cache = get_category_specifics(draft.category_id)
            required_fields = cache.required_fields_json or []
            specifics = draft.item_specifics_json or {}
            for field in required_fields:
                name = field.get("name")
                if name and not specifics.get(name):
                    errors.setdefault("item_specifics", {})
                    errors["item_specifics"][name] = "Required."
        except Exception:
            errors["item_specifics"] = "Unable to validate item specifics."

    return errors


@ebay_list_bp.route("/ebay/list")
@login_required
@require_feature_flag("FEATURE_EBAY_LISTING_CREATE_ENABLED")
@require_plan_feature("create_listings")
def ebay_list_wizard():
    return render_template("ebay_list_wizard.html")


@ebay_list_bp.route("/api/ebay/drafts", methods=["POST"])
@login_required
@require_feature_flag("FEATURE_EBAY_LISTING_CREATE_ENABLED")
@require_plan_feature("create_listings")
def create_draft():
    payload = request.get_json(silent=True) or {}
    locations_result = get_merchant_locations(current_user.id)
    location_data = None
    if locations_result.get("success"):
        if locations_result.get("locations"):
            location_data = locations_result["locations"][0]
    draft = EbayListingDraft(
        user_id=current_user.id,
        status="DRAFT",
        title=payload.get("title"),
        description_html=payload.get("description_html"),
        description_html_sanitized=_sanitize_html(payload.get("description_html")),
        currency=payload.get("currency") or "USD",
        merchant_location_key=(location_data or {}).get("merchantLocationKey"),
        location_postal_code=((location_data or {}).get("location") or {}).get("address", {}).get("postalCode"),
        location_city=((location_data or {}).get("location") or {}).get("address", {}).get("city"),
        location_state=((location_data or {}).get("location") or {}).get("address", {}).get("stateOrProvince"),
        location_country=((location_data or {}).get("location") or {}).get("address", {}).get("country"),
    )
    db.session.add(draft)
    db.session.commit()
    return jsonify({"ok": True, "draft": draft.to_dict()})


@ebay_list_bp.route("/api/ebay/drafts/<int:draft_id>", methods=["GET"])
@login_required
@require_feature_flag("FEATURE_EBAY_LISTING_CREATE_ENABLED")
@require_plan_feature("create_listings")
def get_draft(draft_id):
    draft = _draft_or_404(draft_id)
    if not draft:
        return jsonify({"ok": False, "error": "not_found"}), 404
    return jsonify({"ok": True, "draft": draft.to_dict()})


@ebay_list_bp.route("/api/ebay/drafts/<int:draft_id>", methods=["PATCH"])
@login_required
@require_feature_flag("FEATURE_EBAY_LISTING_CREATE_ENABLED")
@require_plan_feature("create_listings")
def update_draft(draft_id):
    draft = _draft_or_404(draft_id)
    if not draft:
        return jsonify({"ok": False, "error": "not_found"}), 404

    payload = request.get_json(silent=True) or {}
    allowed_fields = {
        "title", "description_html", "category_id",
        "item_specifics", "condition_id", "condition_label", "sku",
        "quantity", "price", "currency",
        "images", "status", "merchant_location_key",
        "fulfillment_policy_id", "payment_policy_id", "return_policy_id",
    }

    for key, value in payload.items():
        if key not in allowed_fields:
            continue
        if key == "description_html":
            draft.description_html = value
            draft.description_html_sanitized = _sanitize_html(value)
        elif key == "item_specifics":
            draft.item_specifics_json = value
        elif key == "images":
            if isinstance(value, list) and len(value) <= 20:
                draft.images_json = value
        elif key in {"fulfillment_policy_id", "payment_policy_id", "return_policy_id"}:
            setattr(draft, key, value)
        else:
            setattr(draft, key, value)

    db.session.commit()
    return jsonify({"ok": True, "draft": draft.to_dict()})


@ebay_list_bp.route("/api/ebay/drafts/<int:draft_id>/validate", methods=["POST"])
@login_required
@require_feature_flag("FEATURE_EBAY_LISTING_CREATE_ENABLED")
@require_plan_feature("create_listings")
def validate_draft(draft_id):
    draft = _draft_or_404(draft_id)
    if not draft:
        return jsonify({"ok": False, "error": "not_found"}), 404
    errors = _validate_draft(draft)
    return jsonify({"ok": len(errors) == 0, "errors": errors})


@ebay_list_bp.route("/api/ebay/drafts/<int:draft_id>/publish", methods=["POST"])
@login_required
@require_feature_flag("FEATURE_EBAY_LISTING_CREATE_ENABLED")
@require_plan_feature("create_listings")
def publish_draft(draft_id):
    if not _rate_limit(f"publish:{current_user.id}", limit=5, window_seconds=300):
        return jsonify({"ok": False, "error": "rate_limited"}), 429
    draft = _draft_or_404(draft_id)
    if not draft:
        return jsonify({"ok": False, "error": "not_found"}), 404

    errors = _validate_draft(draft)
    if errors:
        return jsonify({"ok": False, "errors": errors}), 400

    ebay_cred = MarketplaceCredential.query.filter_by(
        user_id=current_user.id,
        marketplace="ebay",
        is_active=True
    ).first()
    if not ebay_cred:
        return jsonify({"ok": False, "error": "ebay_not_connected"}), 400

    images = _draft_images(draft)
    image_urls = [img.get("ebay_image_url") for img in images if img.get("ebay_image_url")]

    inventory_payload = {
        "availability": {
            "shipToLocationAvailability": {
                "quantity": int(draft.quantity or 0)
            }
        },
        "condition": draft.condition_id,
        "product": {
            "title": draft.title,
            "description": draft.description_html_sanitized or "",
            "aspects": draft.item_specifics_json or {},
            "imageUrls": image_urls,
        },
    }

    inv_result = create_or_replace_inventory_item(current_user.id, draft.sku, inventory_payload)
    if not inv_result.get("success"):
        draft.status = "FAILED"
        draft.last_error = inv_result.get("error")
        db.session.commit()
        return jsonify({"ok": False, "error": "inventory_item_failed", "details": inv_result.get("error")}), 400

    offer_payload = {
        "sku": draft.sku,
        "marketplaceId": "EBAY_US",
        "format": "FIXED_PRICE",
        "availableQuantity": int(draft.quantity or 0),
        "categoryId": draft.category_id,
        "merchantLocationKey": draft.merchant_location_key or "DEFAULT",
        "listingPolicies": {
            "fulfillmentPolicyId": draft.fulfillment_policy_id,
            "paymentPolicyId": draft.payment_policy_id,
            "returnPolicyId": draft.return_policy_id,
        },
        "pricingSummary": {
            "price": {
                "value": str(draft.price),
                "currency": draft.currency or "USD",
            }
        }
    }

    offer_result = create_offer(current_user.id, offer_payload)
    if not offer_result.get("success") or not offer_result.get("offer_id"):
        draft.status = "FAILED"
        draft.last_error = offer_result.get("error")
        db.session.commit()
        return jsonify({"ok": False, "error": "offer_failed", "details": offer_result.get("error")}), 400

    publish_result = publish_offer(current_user.id, offer_result["offer_id"])
    if not publish_result.get("success"):
        draft.status = "FAILED"
        draft.last_error = publish_result.get("error")
        db.session.commit()
        return jsonify({"ok": False, "error": "publish_failed", "details": publish_result.get("error")}), 400

    draft.status = "POSTED"
    draft.ebay_listing_id = publish_result.get("listing_id")
    draft.published_at = publish_result.get("published_at") or datetime.utcnow()
    draft.last_error = None
    db.session.commit()

    return jsonify({"ok": True, "draft": draft.to_dict()})


@ebay_list_bp.route("/api/ebay/drafts/<int:draft_id>/duplicate", methods=["POST"])
@login_required
@require_feature_flag("FEATURE_EBAY_LISTING_CREATE_ENABLED")
@require_plan_feature("create_listings")
def duplicate_draft(draft_id):
    draft = _draft_or_404(draft_id)
    if not draft:
        return jsonify({"ok": False, "error": "not_found"}), 404

    new_draft = EbayListingDraft(
        user_id=current_user.id,
        status="DRAFT",
        title=draft.title,
        description_html=draft.description_html,
        description_html_sanitized=draft.description_html_sanitized,
        description_text=draft.description_text,
        category_id=draft.category_id,
        item_specifics_json=draft.item_specifics_json,
        condition_id=draft.condition_id,
        condition_label=draft.condition_label,
        sku=None,
        quantity=draft.quantity,
        price=draft.price,
        currency=draft.currency,
        location_postal_code=draft.location_postal_code,
        location_city=draft.location_city,
        location_state=draft.location_state,
        location_country=draft.location_country,
        merchant_location_key=draft.merchant_location_key,
        fulfillment_policy_id=draft.fulfillment_policy_id,
        payment_policy_id=draft.payment_policy_id,
        return_policy_id=draft.return_policy_id,
        images_json=draft.images_json,
    )
    db.session.add(new_draft)
    db.session.commit()
    return jsonify({"ok": True, "draft": new_draft.to_dict()})


@ebay_list_bp.route("/api/ebay/images/upload-token", methods=["POST"])
@login_required
@require_feature_flag("FEATURE_EBAY_LISTING_CREATE_ENABLED")
@require_plan_feature("create_listings")
def get_upload_token():
    if not _rate_limit(f"upload:{current_user.id}", limit=20, window_seconds=60):
        return jsonify({"ok": False, "error": "rate_limited"}), 429
    payload = request.get_json(silent=True) or {}
    draft_id = payload.get("draft_id")
    draft = _draft_or_404(int(draft_id)) if draft_id else None
    if not draft:
        return jsonify({"ok": False, "error": "draft_not_found"}), 404

    filename = payload.get("filename") or "image.jpg"
    content_type = payload.get("content_type") or "image/jpeg"
    size = int(payload.get("size") or 0)
    sha256 = payload.get("sha256")

    if size <= 0 or size > 2 * 1024 * 1024:
        return jsonify({"ok": False, "error": "invalid_size"}), 400

    if len(_draft_images(draft)) >= 20:
        return jsonify({"ok": False, "error": "image_limit_reached"}), 400

    result = create_ebay_upload_session(current_user.id, filename, content_type, size, sha256)
    if not result.get("success"):
        return jsonify({"ok": False, "error": result.get("error")}), 400

    return jsonify({"ok": True, "upload": result})


@ebay_list_bp.route("/api/ebay/images/confirm", methods=["POST"])
@login_required
@require_feature_flag("FEATURE_EBAY_LISTING_CREATE_ENABLED")
@require_plan_feature("create_listings")
def confirm_upload():
    payload = request.get_json(silent=True) or {}
    draft_id = payload.get("draft_id")
    draft = _draft_or_404(int(draft_id)) if draft_id else None
    if not draft:
        return jsonify({"ok": False, "error": "draft_not_found"}), 404

    image_entry = payload.get("image") or {}
    images = _draft_images(draft)
    if len(images) >= 20:
        return jsonify({"ok": False, "error": "image_limit_reached"}), 400
    sha256 = image_entry.get("sha256")
    if sha256 and any(img.get("sha256") == sha256 for img in images):
        return jsonify({"ok": True, "draft": draft.to_dict()})

    images.append(image_entry)
    draft.images_json = images
    db.session.commit()
    return jsonify({"ok": True, "draft": draft.to_dict()})


@ebay_list_bp.route("/api/ebay/categories/<category_id>/specifics", methods=["GET"])
@login_required
@require_feature_flag("FEATURE_EBAY_LISTING_CREATE_ENABLED")
@require_plan_feature("create_listings")
def get_category_specifics_api(category_id):
    cache = get_category_specifics(category_id)
    if not cache:
        return jsonify({"ok": False, "error": "not_found"}), 404
    return jsonify({"ok": True, "specifics": cache.to_dict()})


@ebay_list_bp.route("/api/ebay/categories/<category_id>/specifics/refresh", methods=["POST"])
@login_required
@require_feature_flag("FEATURE_EBAY_LISTING_CREATE_ENABLED")
@require_plan_feature("create_listings")
def refresh_category_specifics(category_id):
    cache = get_category_specifics(category_id, force_refresh=True)
    if not cache:
        return jsonify({"ok": False, "error": "not_found"}), 404
    return jsonify({"ok": True, "specifics": cache.to_dict()})


@ebay_list_bp.route("/api/ebay/categories/<category_id>/path", methods=["GET"])
@login_required
@require_feature_flag("FEATURE_EBAY_LISTING_CREATE_ENABLED")
@require_plan_feature("create_listings")
def get_category_path(category_id):
    category = EbayCategory.query.filter_by(category_id=category_id).first()
    if not category:
        return jsonify({"ok": False, "error": "not_found"}), 404
    parts = category.full_path.split(" > ")
    return jsonify({"ok": True, "path": parts, "full_path": category.full_path})


@ebay_list_bp.route("/api/ebay/account/policies", methods=["GET"])
@login_required
@require_feature_flag("FEATURE_EBAY_LISTING_CREATE_ENABLED")
@require_plan_feature("create_listings")
def get_account_policies_api():
    result = get_account_policies(current_user.id)
    if not result.get("success"):
        return jsonify({"ok": False, "error": result.get("error")}), 400
    return jsonify({"ok": True, "policies": result.get("policies")})


@ebay_list_bp.route("/api/ebay/account/locations", methods=["GET"])
@login_required
@require_feature_flag("FEATURE_EBAY_LISTING_CREATE_ENABLED")
@require_plan_feature("create_listings")
def get_account_locations_api():
    result = get_merchant_locations(current_user.id)
    if not result.get("success"):
        return jsonify({"ok": False, "error": result.get("error")}), 400
    return jsonify({"ok": True, "locations": result.get("locations")})
