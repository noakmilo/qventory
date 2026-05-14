from datetime import datetime
import os
import json
import bleach
from flask import Blueprint, jsonify, request, render_template
from flask_login import login_required, current_user
import cloudinary
import cloudinary.uploader
from ..extensions import db
from ..models.ebay_listing_draft import EbayListingDraft
from ..models.ebay_category import EbayCategory
from ..routes.permissions import require_plan_feature, require_feature_flag
from ..helpers.ebay_specifics_cache import get_category_specifics, get_category_condition_options
from ..helpers.ebay_image_upload import create_ebay_upload_session, upload_ebay_image_from_url
from ..helpers.ebay_listing_publish import (
    create_or_replace_inventory_item,
    create_offer,
    update_offer,
    publish_offer,
)
from ..helpers.ebay_account import get_account_policies, get_merchant_locations
from ..models.marketplace_credential import MarketplaceCredential


ebay_list_bp = Blueprint("ebay_list", __name__)

_rate_limits = {}


def _cloudinary_configured() -> bool:
    cloud_name = os.environ.get("CLOUDINARY_CLOUD_NAME")
    api_key = os.environ.get("CLOUDINARY_API_KEY")
    api_secret = os.environ.get("CLOUDINARY_API_SECRET")
    if not (cloud_name and api_key and api_secret):
        return False
    cloudinary.config(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
        secure=True,
    )
    return True


def _delete_cloudinary_public_id(public_id: str | None):
    if not public_id or not _cloudinary_configured():
        return
    try:
        cloudinary.uploader.destroy(public_id, resource_type="image")
    except Exception as exc:
        print(f"[EBAY_LIST] Cloudinary cleanup failed for {public_id}: {exc}")


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
ALLOWED_CONDITION_IDS = {
    "NEW",
    "LIKE_NEW",
    "NEW_OTHER",
    "NEW_WITH_DEFECTS",
    "MANUFACTURER_REFURBISHED",
    "CERTIFIED_REFURBISHED",
    "EXCELLENT_REFURBISHED",
    "VERY_GOOD_REFURBISHED",
    "GOOD_REFURBISHED",
    "SELLER_REFURBISHED",
    "USED_EXCELLENT",
    "USED_VERY_GOOD",
    "USED_GOOD",
    "USED_ACCEPTABLE",
    "FOR_PARTS_OR_NOT_WORKING",
}
ALLOWED_LISTING_FORMATS = {"FIXED_PRICE", "AUCTION"}
AI_SCENARIO = "ai_research"
MAX_DRAFT_IMAGES = 24


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


def _draft_image_source_url(image_entry: dict):
    return (
        image_entry.get("cloudinary_url")
        or image_entry.get("image_url")
        or image_entry.get("url")
        or image_entry.get("ebay_image_url")
    )


def _ensure_draft_images_uploaded_to_ebay(draft: EbayListingDraft):
    images = _draft_images(draft)
    uploaded = []
    changed = False

    for index, image_entry in enumerate(images):
        ebay_url = image_entry.get("ebay_image_url")
        if ebay_url:
            uploaded.append(ebay_url)
            continue

        source_url = _draft_image_source_url(image_entry)
        if not source_url:
            return {"success": False, "error": f"missing_image_source:{index + 1}"}

        result = upload_ebay_image_from_url(
            current_user.id,
            source_url,
            image_entry.get("filename") or f"draft-{draft.id}-{index + 1}.jpg",
        )
        if not result.get("success") or not result.get("image_url"):
            return {
                "success": False,
                "error": result.get("error") or "upload_failed",
                "image_index": index,
            }

        image_entry["ebay_image_url"] = result.get("image_url")
        image_entry["ebay_image_location"] = result.get("location")
        uploaded.append(result.get("image_url"))
        changed = True

    if changed:
        draft.images_json = images
        db.session.commit()

    return {"success": True, "image_urls": uploaded}


def _package_weight_ounces(package_details: dict | None) -> float:
    details = package_details or {}
    try:
        pounds = float(details.get("weight_lbs") or 0)
        ounces = float(details.get("weight_oz") or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, pounds * 16 + ounces)


def _build_package_weight_and_size(package_details: dict | None):
    details = package_details or {}
    total_ounces = _package_weight_ounces(details)
    if total_ounces <= 0:
        return None

    package = {
        "weight": {
            "value": round(total_ounces, 2),
            "unit": "OUNCE",
        }
    }

    try:
        length = float(details.get("length_in") or 0)
        width = float(details.get("width_in") or 0)
        height = float(details.get("height_in") or 0)
    except (TypeError, ValueError):
        length = width = height = 0

    if length > 0 and width > 0 and height > 0:
        package["dimensions"] = {
            "length": round(length, 2),
            "width": round(width, 2),
            "height": round(height, 2),
            "unit": "INCH",
        }

    return package


def _active_listing_format(draft: EbayListingDraft) -> str:
    return draft.listing_format if draft.listing_format in ALLOWED_LISTING_FORMATS else "FIXED_PRICE"


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
    elif draft.condition_id not in ALLOWED_CONDITION_IDS:
        errors["condition_id"] = "Select a valid eBay condition."
    elif draft.category_id:
        try:
            allowed_category_conditions = {
                option["value"]
                for option in get_category_condition_options(str(draft.category_id))
                if option.get("value")
            }
            if allowed_category_conditions and draft.condition_id not in allowed_category_conditions:
                errors["condition_id"] = "This condition is not valid for the selected eBay category."
        except Exception:
            pass

    if not draft.sku:
        errors["sku"] = "SKU is required."

    if not draft.quantity or draft.quantity <= 0:
        errors["quantity"] = "Quantity must be at least 1."

    if draft.price is None or float(draft.price) <= 0:
        if _active_listing_format(draft) == "FIXED_PRICE":
            errors["price"] = "Buy It Now price must be greater than 0."

    if _active_listing_format(draft) == "AUCTION":
        if draft.auction_start_price is None or float(draft.auction_start_price) <= 0:
            errors["auction_start_price"] = "Auction start price must be greater than 0."

    if not draft.currency:
        errors["currency"] = "Currency is required."

    if not draft.fulfillment_policy_id:
        errors["fulfillment_policy_id"] = "Fulfillment policy ID is required."
    if not draft.payment_policy_id:
        errors["payment_policy_id"] = "Payment policy ID is required."
    if not draft.return_policy_id:
        errors["return_policy_id"] = "Return policy ID is required."

    if not draft.merchant_location_key:
        errors["merchant_location_key"] = "Merchant location is required. Create an eBay inventory location first."

    if _package_weight_ounces(draft.package_details_json) <= 0:
        errors["package_weight"] = "Package weight is required."

    images = _draft_images(draft)
    if not images:
        errors["images"] = "At least one image is required."
    else:
        has_ref = any(img.get("cloudinary_url") or img.get("image_url") or img.get("ebay_image_url") for img in images)
        if not has_ref:
            errors["images"] = "Images must be uploaded before publishing."

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


def _openai_client():
    try:
        from openai import OpenAI
    except Exception as exc:
        return None, f"OpenAI library not available: {exc}"

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None, "OpenAI API key not configured."

    try:
        return OpenAI(api_key=api_key), None
    except Exception as exc:
        return None, f"Failed to initialize OpenAI client: {exc}"


def _ai_token_error_response():
    can_use, remaining = current_user.can_use_ai_tokens(AI_SCENARIO)
    if can_use:
        return None
    return jsonify({
        "ok": False,
        "error": "ai_limit_reached",
        "remaining": remaining,
    }), 403


def _parse_ai_json(content: str | None):
    if not content:
        return {}
    text = content.strip()
    if text.startswith("```json"):
        text = text[7:].strip()
    elif text.startswith("```"):
        text = text[3:].strip()
    if text.endswith("```"):
        text = text[:-3].strip()
    return json.loads(text)


def _call_listing_ai(messages, max_tokens=900):
    client, error = _openai_client()
    if error:
        return None, error
    model = os.environ.get("OPENAI_EBAY_LISTING_MODEL", "gpt-4o-mini")
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.25,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    return _parse_ai_json(response.choices[0].message.content), None


def _draft_ai_context(draft: EbayListingDraft):
    return {
        "title": draft.title or "",
        "description_html": draft.description_html_sanitized or draft.description_html or "",
        "category_id": draft.category_id,
        "condition": draft.condition_label or draft.condition_id or "",
        "price": float(draft.price) if draft.price is not None else None,
        "item_specifics": draft.item_specifics_json or {},
    }


def _normalize_ai_specifics(raw_specifics):
    if not isinstance(raw_specifics, dict):
        return {}
    normalized = {}
    for key, value in raw_specifics.items():
        name = str(key).strip()
        if not name:
            continue
        if isinstance(value, list):
            values = [str(v).strip() for v in value if str(v).strip()]
        elif value is None:
            values = []
        else:
            values = [str(value).strip()] if str(value).strip() else []
        if values:
            normalized[name] = values[:5]
    return normalized


@ebay_list_bp.route("/ebay/list")
@login_required
@require_feature_flag("FEATURE_EBAY_LISTING_CREATE_ENABLED")
@require_plan_feature("create_listings")
def ebay_list_wizard():
    return render_template("ebay_list_wizard.html")


@ebay_list_bp.route("/ebay/list/drafts")
@login_required
@require_feature_flag("FEATURE_EBAY_LISTING_CREATE_ENABLED")
@require_plan_feature("create_listings")
def ebay_list_drafts():
    drafts = (
        EbayListingDraft.query
        .filter_by(user_id=current_user.id)
        .order_by(EbayListingDraft.updated_at.desc(), EbayListingDraft.created_at.desc())
        .all()
    )
    return render_template("ebay_list_drafts.html", drafts=drafts)


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
        "listing_format", "accept_offers", "auction_start_price",
        "images", "status", "merchant_location_key",
        "package_details",
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
            if isinstance(value, list) and len(value) <= MAX_DRAFT_IMAGES:
                old_public_ids = {
                    img.get("cloudinary_public_id")
                    for img in _draft_images(draft)
                    if img.get("cloudinary_public_id")
                }
                new_public_ids = {
                    img.get("cloudinary_public_id")
                    for img in value
                    if isinstance(img, dict) and img.get("cloudinary_public_id")
                }
                for public_id in old_public_ids - new_public_ids:
                    _delete_cloudinary_public_id(public_id)
                draft.images_json = value
        elif key == "package_details":
            draft.package_details_json = value if isinstance(value, dict) else {}
        elif key == "listing_format":
            draft.listing_format = value if value in ALLOWED_LISTING_FORMATS else "FIXED_PRICE"
        elif key == "accept_offers":
            draft.accept_offers = bool(value)
        elif key in {"price", "auction_start_price"}:
            setattr(draft, key, None if value is None or value == "" else value)
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


@ebay_list_bp.route("/api/ebay/drafts/<int:draft_id>/ai/title", methods=["POST"])
@login_required
@require_feature_flag("FEATURE_EBAY_LISTING_CREATE_ENABLED")
@require_plan_feature("create_listings")
def ai_optimize_title(draft_id):
    draft = _draft_or_404(draft_id)
    if not draft:
        return jsonify({"ok": False, "error": "not_found"}), 404
    token_error = _ai_token_error_response()
    if token_error:
        return token_error

    context = _draft_ai_context(draft)
    if not context["title"]:
        return jsonify({"ok": False, "error": "title_required"}), 400

    messages = [
        {
            "role": "system",
            "content": (
                "You optimize eBay listing titles. Return only JSON with key title. "
                "The title must be natural, search-friendly, no keyword stuffing, and 80 characters or fewer."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(context, ensure_ascii=True),
        },
    ]
    try:
        data, error = _call_listing_ai(messages, max_tokens=220)
    except Exception as exc:
        return jsonify({"ok": False, "error": "openai_error", "details": str(exc)}), 500
    if error:
        return jsonify({"ok": False, "error": error}), 500

    title = str((data or {}).get("title") or "").strip()[:80]
    if not title:
        return jsonify({"ok": False, "error": "empty_ai_response"}), 502
    current_user.consume_ai_tokens(AI_SCENARIO)
    return jsonify({"ok": True, "title": title})


@ebay_list_bp.route("/api/ebay/drafts/<int:draft_id>/ai/description", methods=["POST"])
@login_required
@require_feature_flag("FEATURE_EBAY_LISTING_CREATE_ENABLED")
@require_plan_feature("create_listings")
def ai_generate_description(draft_id):
    draft = _draft_or_404(draft_id)
    if not draft:
        return jsonify({"ok": False, "error": "not_found"}), 404
    token_error = _ai_token_error_response()
    if token_error:
        return token_error

    context = _draft_ai_context(draft)
    if not context["title"]:
        return jsonify({"ok": False, "error": "title_required"}), 400

    image_url = None
    images = _draft_images(draft)
    if images:
        image_url = _draft_image_source_url(images[0])

    prompt = (
        "Create an enriched eBay item description from this listing context. "
        "Be accurate and do not invent exact specs not visible or provided. "
        "Return only JSON with key description_html. Use simple HTML tags: p, ul, li, strong."
    )
    user_content = [{"type": "text", "text": f"{prompt}\n\nContext:\n{json.dumps(context, ensure_ascii=True)}"}]
    if image_url:
        user_content.append({"type": "image_url", "image_url": {"url": image_url}})

    messages = [
        {"role": "system", "content": "You write concise, buyer-friendly eBay descriptions and return strict JSON."},
        {"role": "user", "content": user_content},
    ]
    try:
        data, error = _call_listing_ai(messages, max_tokens=900)
    except Exception as exc:
        return jsonify({"ok": False, "error": "openai_error", "details": str(exc)}), 500
    if error:
        return jsonify({"ok": False, "error": error}), 500

    description_html = _sanitize_html((data or {}).get("description_html"))
    if not description_html:
        return jsonify({"ok": False, "error": "empty_ai_response"}), 502
    current_user.consume_ai_tokens(AI_SCENARIO)
    return jsonify({"ok": True, "description_html": description_html})


@ebay_list_bp.route("/api/ebay/drafts/<int:draft_id>/ai/specifics", methods=["POST"])
@login_required
@require_feature_flag("FEATURE_EBAY_LISTING_CREATE_ENABLED")
@require_plan_feature("create_listings")
def ai_fill_specifics(draft_id):
    draft = _draft_or_404(draft_id)
    if not draft:
        return jsonify({"ok": False, "error": "not_found"}), 404
    token_error = _ai_token_error_response()
    if token_error:
        return token_error
    if not draft.category_id:
        return jsonify({"ok": False, "error": "category_required"}), 400

    try:
        specifics_schema = get_category_specifics(draft.category_id).to_dict()
    except Exception as exc:
        return jsonify({"ok": False, "error": "specifics_lookup_failed", "details": str(exc)}), 500

    context = _draft_ai_context(draft)
    messages = [
        {
            "role": "system",
            "content": (
                "You fill eBay item specifics from title and description. "
                "Use only fields present in the provided schema. Do not guess unknown brand, model, size, or year. "
                "Return JSON with key item_specifics where each value is an array of strings."
            ),
        },
        {
            "role": "user",
            "content": json.dumps({
                "listing": context,
                "specifics_schema": {
                    "required_fields": specifics_schema.get("required_fields", []),
                    "optional_fields": specifics_schema.get("optional_fields", [])[:40],
                },
            }, ensure_ascii=True),
        },
    ]
    try:
        data, error = _call_listing_ai(messages, max_tokens=1000)
    except Exception as exc:
        return jsonify({"ok": False, "error": "openai_error", "details": str(exc)}), 500
    if error:
        return jsonify({"ok": False, "error": error}), 500

    current = draft.item_specifics_json or {}
    generated = _normalize_ai_specifics((data or {}).get("item_specifics"))
    merged = {**current, **generated}
    current_user.consume_ai_tokens(AI_SCENARIO)
    return jsonify({"ok": True, "item_specifics": merged})


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
    image_upload_result = _ensure_draft_images_uploaded_to_ebay(draft)
    if not image_upload_result.get("success"):
        draft.status = "FAILED"
        draft.last_error = image_upload_result.get("error")
        db.session.commit()
        return jsonify({
            "ok": False,
            "error": "image_upload_failed",
            "details": image_upload_result.get("error"),
            "image_index": image_upload_result.get("image_index"),
        }), 400

    image_urls = image_upload_result.get("image_urls") or []

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
    package_weight_and_size = _build_package_weight_and_size(draft.package_details_json)
    if package_weight_and_size:
        inventory_payload["packageWeightAndSize"] = package_weight_and_size

    inv_result = create_or_replace_inventory_item(current_user.id, draft.sku, inventory_payload)
    if not inv_result.get("success"):
        draft.status = "FAILED"
        draft.last_error = inv_result.get("error")
        db.session.commit()
        return jsonify({"ok": False, "error": "inventory_item_failed", "details": inv_result.get("error")}), 400

    listing_format = _active_listing_format(draft)
    pricing_summary = {}
    if listing_format == "AUCTION":
        pricing_summary["auctionStartPrice"] = {
            "value": str(draft.auction_start_price),
            "currency": draft.currency or "USD",
        }
    else:
        pricing_summary["price"] = {
            "value": str(draft.price),
            "currency": draft.currency or "USD",
        }

    listing_policies = {
        "fulfillmentPolicyId": draft.fulfillment_policy_id,
        "paymentPolicyId": draft.payment_policy_id,
        "returnPolicyId": draft.return_policy_id,
    }
    if listing_format == "FIXED_PRICE" and draft.accept_offers:
        listing_policies["bestOfferTerms"] = {"bestOfferEnabled": True}

    offer_payload = {
        "sku": draft.sku,
        "marketplaceId": "EBAY_US",
        "format": listing_format,
        "availableQuantity": int(draft.quantity or 0),
        "categoryId": draft.category_id,
        "merchantLocationKey": draft.merchant_location_key,
        "listingPolicies": listing_policies,
        "pricingSummary": pricing_summary,
    }

    offer_result = create_offer(current_user.id, offer_payload)
    if not offer_result.get("success") and offer_result.get("existing_offer_id"):
        offer_result = update_offer(
            current_user.id,
            offer_result["existing_offer_id"],
            offer_payload,
        )

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
        listing_format=draft.listing_format,
        accept_offers=draft.accept_offers,
        auction_start_price=draft.auction_start_price,
        location_postal_code=draft.location_postal_code,
        location_city=draft.location_city,
        location_state=draft.location_state,
        location_country=draft.location_country,
        merchant_location_key=draft.merchant_location_key,
        fulfillment_policy_id=draft.fulfillment_policy_id,
        payment_policy_id=draft.payment_policy_id,
        return_policy_id=draft.return_policy_id,
        package_details_json=draft.package_details_json,
        images_json=draft.images_json,
    )
    db.session.add(new_draft)
    db.session.commit()
    return jsonify({"ok": True, "draft": new_draft.to_dict()})


@ebay_list_bp.route("/api/ebay/drafts/<int:draft_id>", methods=["DELETE"])
@login_required
@require_feature_flag("FEATURE_EBAY_LISTING_CREATE_ENABLED")
@require_plan_feature("create_listings")
def delete_draft(draft_id):
    draft = _draft_or_404(draft_id)
    if not draft:
        return jsonify({"ok": False, "error": "not_found"}), 404
    if draft.status == "POSTED":
        return jsonify({"ok": False, "error": "posted_drafts_cannot_be_deleted"}), 400

    db.session.delete(draft)
    db.session.commit()
    return jsonify({"ok": True})


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

    if len(_draft_images(draft)) >= MAX_DRAFT_IMAGES:
        return jsonify({"ok": False, "error": "image_limit_reached"}), 400

    result = create_ebay_upload_session(current_user.id, filename, content_type, size, sha256)
    if not result.get("success"):
        return jsonify({"ok": False, "error": result.get("error")}), 400

    return jsonify({"ok": True, "upload": result})


@ebay_list_bp.route("/api/ebay/images/upload", methods=["POST"])
@login_required
@require_feature_flag("FEATURE_EBAY_LISTING_CREATE_ENABLED")
@require_plan_feature("create_listings")
def upload_image():
    if not _rate_limit(f"upload:{current_user.id}", limit=20, window_seconds=60):
        return jsonify({"ok": False, "error": "rate_limited"}), 429

    draft_id = request.form.get("draft_id")
    draft = _draft_or_404(int(draft_id)) if draft_id else None
    if not draft:
        return jsonify({"ok": False, "error": "draft_not_found"}), 404

    image_file = request.files.get("image")
    if not image_file:
        return jsonify({"ok": False, "error": "missing_image"}), 400
    if not _cloudinary_configured():
        return jsonify({"ok": False, "error": "cloudinary_not_configured"}), 503

    images = _draft_images(draft)
    replace_index = request.form.get("replace_index")
    try:
        replace_index = int(replace_index) if replace_index not in {None, ""} else None
    except (TypeError, ValueError):
        replace_index = None
    is_replacement = replace_index is not None and 0 <= replace_index < len(images)
    if len(images) >= MAX_DRAFT_IMAGES and not is_replacement:
        return jsonify({"ok": False, "error": "image_limit_reached"}), 400

    sha256 = request.form.get("sha256")
    if sha256 and not is_replacement and any(img.get("sha256") == sha256 for img in images):
        return jsonify({"ok": True, "draft": draft.to_dict(), "image": next(img for img in images if img.get("sha256") == sha256)})

    image_file.stream.seek(0, 2)
    size = image_file.stream.tell()
    image_file.stream.seek(0)
    if size <= 0 or size > 8 * 1024 * 1024:
        return jsonify({"ok": False, "error": "invalid_size"}), 400

    try:
        public_id = f"ebay_drafts/user_{current_user.id}/draft_{draft.id}/{sha256 or int(datetime.utcnow().timestamp())}"
        result = cloudinary.uploader.upload(
            image_file.stream,
            public_id=public_id,
            overwrite=True,
            resource_type="image",
            format="jpg",
            transformation=[{"quality": "auto:good"}],
            tags=["ebay_listing_draft", f"user_{current_user.id}", f"draft_{draft.id}"],
            context=f"user_id={current_user.id}|draft_id={draft.id}|source=ebay_listing_draft",
        )
    except Exception as exc:
        return jsonify({"ok": False, "error": "cloudinary_upload_failed", "details": str(exc)}), 502

    image_entry = {
        "filename": request.form.get("filename") or image_file.filename or "image.jpg",
        "sha256": sha256,
        "width": result.get("width") or int(request.form.get("width") or 0) or None,
        "height": result.get("height") or int(request.form.get("height") or 0) or None,
        "cloudinary_url": result.get("secure_url") or result.get("url"),
        "cloudinary_public_id": result.get("public_id"),
        "image_url": result.get("secure_url") or result.get("url"),
        "ebay_image_url": None,
        "ebay_image_location": None,
        "is_main": len(images) == 0,
    }
    if is_replacement:
        image_entry["is_main"] = bool(images[replace_index].get("is_main"))
        _delete_cloudinary_public_id(images[replace_index].get("cloudinary_public_id"))
        images[replace_index] = image_entry
    else:
        images.append(image_entry)
    draft.images_json = images
    db.session.commit()

    return jsonify({"ok": True, "draft": draft.to_dict(), "image": image_entry})


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
    if len(images) >= MAX_DRAFT_IMAGES:
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


@ebay_list_bp.route("/api/ebay/categories/<category_id>/conditions", methods=["GET"])
@login_required
@require_feature_flag("FEATURE_EBAY_LISTING_CREATE_ENABLED")
@require_plan_feature("create_listings")
def get_category_conditions_api(category_id):
    try:
        options = get_category_condition_options(str(category_id))
    except Exception as exc:
        print(f"[EBAY_LIST] Condition lookup failed for category {category_id}: {exc}")
        return jsonify({"ok": False, "error": "condition_lookup_failed", "details": str(exc)}), 500
    return jsonify({"ok": True, "conditions": options})


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
