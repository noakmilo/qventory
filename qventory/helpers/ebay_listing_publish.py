import requests
from datetime import datetime
from .ebay_inventory import get_user_access_token, EBAY_API_BASE


def _headers(access_token: str):
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }


def create_or_replace_inventory_item(user_id: int, sku: str, payload: dict) -> dict:
    access_token = get_user_access_token(user_id)
    if not access_token:
        return {"success": False, "error": "missing_access_token"}

    url = f"{EBAY_API_BASE}/sell/inventory/v1/inventory_item/{sku}"
    resp = requests.put(url, headers=_headers(access_token), json=payload, timeout=30)
    if resp.status_code >= 400:
        return {"success": False, "error": resp.text}
    return {"success": True, "response": resp.json() if resp.text else {}}


def create_offer(user_id: int, payload: dict) -> dict:
    access_token = get_user_access_token(user_id)
    if not access_token:
        return {"success": False, "error": "missing_access_token"}

    url = f"{EBAY_API_BASE}/sell/inventory/v1/offer"
    resp = requests.post(url, headers=_headers(access_token), json=payload, timeout=30)
    if resp.status_code >= 400:
        return {"success": False, "error": resp.text}
    data = resp.json() if resp.text else {}
    return {"success": True, "offer_id": data.get("offerId"), "response": data}


def publish_offer(user_id: int, offer_id: str) -> dict:
    access_token = get_user_access_token(user_id)
    if not access_token:
        return {"success": False, "error": "missing_access_token"}

    url = f"{EBAY_API_BASE}/sell/inventory/v1/offer/{offer_id}/publish"
    resp = requests.post(url, headers=_headers(access_token), timeout=30)
    if resp.status_code >= 400:
        return {"success": False, "error": resp.text}
    data = resp.json() if resp.text else {}
    return {
        "success": True,
        "listing_id": data.get("listingId"),
        "response": data,
        "published_at": datetime.utcnow(),
    }
