import requests
from datetime import datetime, timedelta
from sqlalchemy.exc import IntegrityError
from ..extensions import db
from ..models.ebay_category import EbayCategory
from ..models.ebay_category_specific_cache import EbayCategorySpecificCache
from .ebay_oauth import get_ebay_oauth


DEFAULT_SPECIFICS_TTL_DAYS = 30

CONDITION_ID_TO_INVENTORY_ENUM = {
    "1000": "NEW",
    "1500": "NEW_OTHER",
    "1750": "NEW_WITH_DEFECTS",
    "2000": "MANUFACTURER_REFURBISHED",
    "2010": "EXCELLENT_REFURBISHED",
    "2020": "VERY_GOOD_REFURBISHED",
    "2030": "GOOD_REFURBISHED",
    "2500": "SELLER_REFURBISHED",
    "2750": "LIKE_NEW",
    "3000": "USED_EXCELLENT",
    "4000": "USED_VERY_GOOD",
    "5000": "USED_GOOD",
    "6000": "USED_ACCEPTABLE",
    "7000": "FOR_PARTS_OR_NOT_WORKING",
}

CONDITION_ENUM_LABELS = {
    "NEW": "New",
    "LIKE_NEW": "Like New",
    "NEW_OTHER": "New Other",
    "NEW_WITH_DEFECTS": "New With Defects",
    "MANUFACTURER_REFURBISHED": "Manufacturer Refurbished",
    "CERTIFIED_REFURBISHED": "Certified Refurbished",
    "EXCELLENT_REFURBISHED": "Excellent Refurbished",
    "VERY_GOOD_REFURBISHED": "Very Good Refurbished",
    "GOOD_REFURBISHED": "Good Refurbished",
    "SELLER_REFURBISHED": "Seller Refurbished",
    "USED_EXCELLENT": "Used",
    "USED_VERY_GOOD": "Used - Very Good",
    "USED_GOOD": "Used - Good",
    "USED_ACCEPTABLE": "Used - Acceptable",
    "FOR_PARTS_OR_NOT_WORKING": "For Parts or Not Working",
}


def _get_category_tree_id(marketplace_id: str) -> str:
    # Prefer cached tree_id from existing categories
    cat = EbayCategory.query.filter(EbayCategory.tree_id.isnot(None)).first()
    if cat and cat.tree_id:
        return cat.tree_id

    oauth = get_ebay_oauth()
    headers = oauth.get_auth_header()
    resp = requests.get(
        f"{oauth.api_endpoint}/commerce/taxonomy/v1/get_default_category_tree_id",
        headers=headers,
        params={"marketplace_id": marketplace_id},
        timeout=15
    )
    resp.raise_for_status()
    data = resp.json()
    tree_id = data.get("categoryTreeId")
    if not tree_id:
        raise ValueError("Missing categoryTreeId from eBay taxonomy API")
    return tree_id


def _fetch_specifics_from_ebay(category_id: str, marketplace_id: str) -> dict:
    oauth = get_ebay_oauth()
    headers = oauth.get_auth_header()
    tree_id = _get_category_tree_id(marketplace_id)
    url = f"{oauth.api_endpoint}/commerce/taxonomy/v1/category_tree/{tree_id}/get_item_aspects_for_category"
    resp = requests.get(
        url,
        headers=headers,
        params={"category_id": category_id},
        timeout=20
    )
    resp.raise_for_status()
    data = resp.json() or {}
    aspects = data.get("aspects") or []
    required = []
    optional = []
    for aspect in aspects:
        name = aspect.get("localizedAspectName") or aspect.get("aspectName")
        values = [
            {
                "value": v.get("localizedValue") or v.get("value"),
                "value_id": v.get("valueId"),
            }
            for v in (aspect.get("aspectValues") or [])
            if v.get("localizedValue") or v.get("value")
        ]
        entry = {
            "name": name,
            "values": values,
            "mode": (aspect.get("aspectConstraint") or {}).get("aspectMode"),
        }
        if (aspect.get("aspectConstraint") or {}).get("aspectRequired"):
            required.append(entry)
        else:
            optional.append(entry)
    return {
        "required": required,
        "optional": optional,
        "source_version": data.get("aspectVersion") or data.get("categoryTreeVersion"),
    }


def get_category_specifics(category_id: str, marketplace_id: str = "EBAY_US", force_refresh: bool = False):
    now = datetime.utcnow()
    cache = EbayCategorySpecificCache.query.filter_by(
        category_id=category_id,
        marketplace_id=marketplace_id
    ).first()

    if cache and not force_refresh:
        if not cache.expires_at or cache.expires_at > now:
            return cache

    payload = _fetch_specifics_from_ebay(category_id, marketplace_id)
    expires_at = now + timedelta(days=DEFAULT_SPECIFICS_TTL_DAYS)

    if cache:
        cache.required_fields_json = payload["required"]
        cache.optional_fields_json = payload["optional"]
        cache.fetched_at = now
        cache.expires_at = expires_at
        cache.source_version = payload.get("source_version")
        db.session.commit()
        return cache

    cache = EbayCategorySpecificCache(
        category_id=category_id,
        marketplace_id=marketplace_id,
        required_fields_json=payload["required"],
        optional_fields_json=payload["optional"],
        fetched_at=now,
        expires_at=expires_at,
        source_version=payload.get("source_version"),
    )
    db.session.add(cache)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        cache = EbayCategorySpecificCache.query.filter_by(
            category_id=category_id,
            marketplace_id=marketplace_id
        ).first()
    return cache


def get_category_condition_options(category_id: str, marketplace_id: str = "EBAY_US") -> list[dict]:
    oauth = get_ebay_oauth()
    headers = oauth.get_auth_header()
    tree_id = _get_category_tree_id(marketplace_id)
    url = f"{oauth.api_endpoint}/commerce/taxonomy/v1/category_tree/{tree_id}/get_item_condition_policies"
    resp = requests.get(
        url,
        headers=headers,
        params={"category_id": category_id},
        timeout=20
    )
    resp.raise_for_status()
    data = resp.json() or {}
    policies = data.get("itemConditionPolicies") or data.get("conditionPolicies") or []
    options = []
    seen = set()
    for policy in policies:
        condition_id = str(policy.get("conditionId") or policy.get("itemConditionId") or "")
        value = CONDITION_ID_TO_INVENTORY_ENUM.get(condition_id)
        raw_label = (
            policy.get("conditionDescription")
            or policy.get("localizedConditionName")
            or policy.get("conditionDisplayName")
            or ""
        )
        if condition_id == "2000" and "certified" in raw_label.lower():
            value = "CERTIFIED_REFURBISHED"
        if not value or value in seen:
            continue
        label = (
            raw_label
            or CONDITION_ENUM_LABELS.get(value)
            or value.replace("_", " ").title()
        )
        options.append({
            "value": value,
            "label": label,
            "condition_id": condition_id,
        })
        seen.add(value)
    return options
