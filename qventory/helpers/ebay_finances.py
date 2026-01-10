"""
Helpers for eBay Finances API (payouts and transactions).
"""
from datetime import datetime, timedelta
import requests

from qventory.helpers.ebay_inventory import get_user_access_token, EBAY_API_BASE, log_inv


def _format_iso(dt):
    if not dt:
        return None
    if isinstance(dt, datetime):
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt


def _fetch_finances_endpoint(user_id, path, params):
    token = get_user_access_token(user_id)
    if not token:
        return {'success': False, 'error': 'missing_access_token', 'data': []}

    url = f"{EBAY_API_BASE}{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=20)
    except requests.RequestException as exc:
        return {'success': False, 'error': str(exc), 'data': []}

    if response.status_code != 200:
        body_preview = response.text[:500] if response.text else ""
        correlation_id = response.headers.get("x-ebay-correlation-id")
        log_inv(
            f"Finances API error {response.status_code} "
            f"(correlation_id={correlation_id}): {body_preview}"
        )
        if response.status_code == 404:
            return {
                'success': False,
                'error': 'finances_api_unavailable',
                'data': []
            }
        if response.status_code == 403:
            return {
                'success': False,
                'error': 'finances_api_forbidden',
                'data': []
            }
        return {'success': False, 'error': response.text or 'unknown_error', 'data': []}

    try:
        payload = response.json()
    except ValueError:
        return {'success': False, 'error': 'invalid_json', 'data': []}

    return {'success': True, 'data': payload}


def fetch_ebay_payouts(user_id, start_date, end_date, limit=200, offset=0):
    start_iso = _format_iso(start_date)
    end_iso = _format_iso(end_date)
    filters = []
    if start_iso and end_iso:
        filters.append(f"payoutDate:[{start_iso}..{end_iso}]")

    params = {
        "limit": limit,
        "offset": offset
    }
    if filters:
        params["filter"] = ",".join(filters)

    result = _fetch_finances_endpoint(user_id, "/sell/finances/v1/payout", params)
    if not result.get('success'):
        return {'success': False, 'error': result.get('error'), 'payouts': []}

    payload = result.get('data', {}) or {}
    payouts = payload.get('payouts', []) or []
    return {'success': True, 'payouts': payouts, 'total': payload.get('total')}


def fetch_ebay_transactions(user_id, start_date, end_date, limit=200, offset=0):
    start_iso = _format_iso(start_date)
    end_iso = _format_iso(end_date)
    filters = []
    if start_iso and end_iso:
        filters.append(f"transactionDate:[{start_iso}..{end_iso}]")

    params = {
        "limit": limit,
        "offset": offset
    }
    if filters:
        params["filter"] = ",".join(filters)

    result = _fetch_finances_endpoint(user_id, "/sell/finances/v1/transaction", params)
    if not result.get('success'):
        return {'success': False, 'error': result.get('error'), 'transactions': []}

    payload = result.get('data', {}) or {}
    transactions = payload.get('transactions', []) or []
    return {'success': True, 'transactions': transactions, 'total': payload.get('total')}


def fetch_all_ebay_payouts(user_id, start_date, end_date, limit=200, max_pages=10):
    payouts = []
    offset = 0
    for _ in range(max_pages):
        result = fetch_ebay_payouts(user_id, start_date, end_date, limit=limit, offset=offset)
        if not result.get('success'):
            return {'success': False, 'error': result.get('error'), 'payouts': payouts}
        page = result.get('payouts', []) or []
        payouts.extend(page)
        if len(page) < limit:
            break
        offset += limit
    return {'success': True, 'payouts': payouts}


def fetch_all_ebay_transactions(user_id, start_date, end_date, limit=200, max_pages=10):
    transactions = []
    offset = 0
    for _ in range(max_pages):
        result = fetch_ebay_transactions(user_id, start_date, end_date, limit=limit, offset=offset)
        if not result.get('success'):
            return {'success': False, 'error': result.get('error'), 'transactions': transactions}
        page = result.get('transactions', []) or []
        transactions.extend(page)
        if len(page) < limit:
            break
        offset += limit
    return {'success': True, 'transactions': transactions}
