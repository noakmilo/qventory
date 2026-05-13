import os
import requests
from datetime import datetime, timedelta
from .ebay_inventory import get_user_access_token, EBAY_API_BASE, EBAY_ENV


def _media_api_base():
    if EBAY_ENV == "production":
        return "https://apim.ebay.com"
    return "https://apim.sandbox.ebay.com"


def upload_ebay_image_file(user_id: int, file_obj, filename: str, content_type: str | None):
    """
    Upload an image to eBay Picture Services and return the EPS URL used by Inventory API listings.
    """
    access_token = get_user_access_token(user_id)
    if not access_token:
        return {"success": False, "error": "missing_access_token"}

    url = f"{_media_api_base()}/commerce/media/v1_beta/image/create_image_from_file"
    headers = {"Authorization": f"Bearer {access_token}"}
    files = {
        "image": (
            filename or "image.jpg",
            file_obj,
            content_type or "image/jpeg",
        )
    }
    resp = requests.post(url, headers=headers, files=files, timeout=60)
    if resp.status_code >= 400:
        return {"success": False, "error": resp.text, "status_code": resp.status_code}

    data = resp.json() if resp.text else {}
    return {
        "success": True,
        "image_url": data.get("imageUrl") or data.get("maxDimensionImageUrl"),
        "max_dimension_image_url": data.get("maxDimensionImageUrl"),
        "location": resp.headers.get("Location"),
        "response": data,
    }


def create_ebay_upload_session(user_id: int, filename: str, content_type: str, size: int, sha256: str | None):
    """
    Create an eBay upload session for direct browser uploads.
    Uses the Commerce Media API (beta) when available.
    """
    access_token = get_user_access_token(user_id)
    if not access_token:
        return {"success": False, "error": "missing_access_token"}

    api_base = EBAY_API_BASE
    url = f"{api_base}/commerce/media/v1_beta/upload_session"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    body = {
        "fileName": filename,
        "fileSize": size,
        "contentType": content_type or "image/jpeg",
    }
    if sha256:
        body["checksum"] = sha256

    resp = requests.post(url, headers=headers, json=body, timeout=20)
    if resp.status_code >= 400:
        return {"success": False, "error": resp.text}

    data = resp.json() or {}
    expires_at = None
    if data.get("expirationDate"):
        try:
            expires_at = datetime.fromisoformat(data["expirationDate"].replace("Z", "+00:00"))
        except Exception:
            expires_at = datetime.utcnow() + timedelta(minutes=30)

    return {
        "success": True,
        "upload_url": data.get("uploadUrl"),
        "upload_session_id": data.get("uploadSessionId"),
        "expires_at": expires_at.isoformat() if expires_at else None,
        "headers": data.get("headers") or {},
    }


def confirm_upload_reference(upload_session_id: str, image_url: str | None):
    return {
        "upload_session_id": upload_session_id,
        "image_url": image_url,
    }
