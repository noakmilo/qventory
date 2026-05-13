import requests
from .ebay_inventory import get_user_access_token, EBAY_API_BASE


def _headers(token: str):
    return {"Authorization": f"Bearer {token}"}


def get_account_policies(user_id: int, marketplace_id: str = "EBAY_US") -> dict:
    token = get_user_access_token(user_id)
    if not token:
        return {"success": False, "error": "missing_access_token"}

    base = f"{EBAY_API_BASE}/sell/account/v1"
    policies = {}
    for policy_type, endpoint in [
        ("fulfillment", "fulfillment_policy"),
        ("payment", "payment_policy"),
        ("return", "return_policy"),
    ]:
        resp = requests.get(
            f"{base}/{endpoint}",
            headers=_headers(token),
            params={"marketplace_id": marketplace_id},
            timeout=20
        )
        if resp.status_code >= 400:
            return {"success": False, "error": resp.text}
        data = resp.json() or {}
        list_key = {
            "fulfillment": "fulfillmentPolicies",
            "payment": "paymentPolicies",
            "return": "returnPolicies",
        }[policy_type]
        id_key = {
            "fulfillment": "fulfillmentPolicyId",
            "payment": "paymentPolicyId",
            "return": "returnPolicyId",
        }[policy_type]
        normalized = []
        for policy in data.get(list_key, data.get("policies", [])):
            entry = dict(policy)
            entry["id"] = entry.get(id_key) or entry.get("policyId") or entry.get("id")
            entry["name"] = entry.get("name") or entry.get("description") or entry.get("id")
            normalized.append(entry)
        policies[policy_type] = normalized

    return {"success": True, "policies": policies}


def get_merchant_locations(user_id: int) -> dict:
    token = get_user_access_token(user_id)
    if not token:
        return {"success": False, "error": "missing_access_token"}

    url = f"{EBAY_API_BASE}/sell/inventory/v1/location"
    resp = requests.get(url, headers=_headers(token), params={"limit": 200}, timeout=20)
    if resp.status_code >= 400:
        return {"success": False, "error": resp.text}

    return {"success": True, "locations": resp.json().get("locations", [])}
