import os
import requests
from datetime import datetime, timedelta
from .ebay_inventory import get_user_access_token, EBAY_API_BASE


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
