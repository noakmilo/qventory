"""
Shippo Tracking Integration

Provides helpers to fetch multi-carrier tracking information from Shippo's API
and annotate fulfillment orders with rich status data.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple

import requests
from dateutil import parser as date_parser
from flask import current_app

API_BASE_URL = "https://api.goshippo.com"

# Mapping of common carrier display names to Shippo slugs
CARRIER_ALIASES: Dict[str, str] = {
    "usps": "usps",
    "united states postal service": "usps",
    "ups": "ups",
    "united parcel service": "ups",
    "fedex": "fedex",
    "fedex smartpost": "fedex_smartpost",
    "dhl": "dhl_express",
    "dhl express": "dhl_express",
    "dhl ecommerce": "dhl_ecommerce",
    "dhl e-commerce": "dhl_ecommerce",
    "lasership": "lasership",
    "canada post": "canada_post",
    "canadapost": "canada_post",
    "ontrac": "ontrac",
    "purolator": "purolator",
    "postnl": "postnl",
    "royal mail": "royal_mail",
    "yodel": "yodel",
    "gls": "gls",
    "hermes": "hermes",
    "parcelforce": "parcelforce",
    "aramex": "aramex",
    "auspost": "auspost",
    "australia post": "auspost",
    "tnt": "tnt",
}

# Mapping Shippo status codes to simplified badges we can present in the UI
STATUS_NORMALIZATION: Dict[str, str] = {
    "DELIVERED": "delivered",
    "TRANSIT": "in_transit",
    "OUT FOR DELIVERY": "in_transit",
    "OUT_FOR_DELIVERY": "in_transit",
    "DELIVERY": "in_transit",
    "SHIPPING": "label_created",
    "PRE_TRANSIT": "label_created",
    "UNKNOWN": "unknown",
    "EXCEPTION": "exception",
    "FAILURE": "exception",
    "RETURNED": "returned",
    "CANCELLED": "cancelled",
    "DELIVERY DELAYED": "in_transit",
    "DELIVERY_DELAYED": "in_transit",
    "AVAILABLE FOR PICKUP": "in_transit",
    "AVAILABLE_FOR_PICKUP": "in_transit",
    "HELD": "held",
    "CUSTOMS": "held",
}


BADGE_STYLES: Dict[str, Dict[str, str]] = {
    "delivered": {"label": "Delivered", "bg": "#d1fae5", "fg": "#065f46"},
    "in_transit": {"label": "In Transit", "bg": "#fef3c7", "fg": "#92400e"},
    "label_created": {"label": "Label Created", "bg": "#e0f2fe", "fg": "#0369a1"},
    "returned": {"label": "Returned", "bg": "#fef3c7", "fg": "#713f12"},
    "exception": {"label": "Exception", "bg": "#fee2e2", "fg": "#991b1b"},
    "cancelled": {"label": "Cancelled", "bg": "#f3f4f6", "fg": "#1f2937"},
    "held": {"label": "Held", "bg": "#fef3c7", "fg": "#92400e"},
    "unknown": {"label": "Status Unknown", "bg": "#e5e7eb", "fg": "#374151"},
    "missing": {"label": "No Tracking", "bg": "#e5e7eb", "fg": "#4b5563"},
}


def normalize_carrier(carrier_name: Optional[str]) -> Optional[str]:
    if not carrier_name:
        return None
    key = carrier_name.strip().lower()
    if not key:
        return None
    return CARRIER_ALIASES.get(key, key.replace(" ", "_"))


def parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = date_parser.isoparse(value)
    except (ValueError, TypeError):
        return None

    if parsed.tzinfo:
        # Convert to UTC then drop tzinfo for easier rendering
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _create_track(
    tracking_number: str,
    carrier: Optional[str],
    headers: Dict[str, str],
    errors: Optional[List[str]] = None,
) -> Optional[dict]:
    payload = {"tracking_number": tracking_number}
    if carrier:
        payload["carrier"] = carrier

    try:
        response = requests.post(
            f"{API_BASE_URL}/tracks/",
            headers=headers,
            json=payload,
            timeout=15,
        )
    except requests.RequestException as exc:
        current_app.logger.warning("Shippo track creation failed: %s", exc)
        if errors is not None:
            errors.append(f"{tracking_number}: network error ({exc})")
        return None

    if response.status_code in (200, 201, 202):
        return response.json()

    # Already tracked is considered success for our use case
    if response.status_code == 400:
        try:
            data = response.json()
        except ValueError:
            data = {}
        detail = (data or {}).get("detail", "")
        if isinstance(detail, str) and "already being tracked" in detail.lower():
            return data

    message = response.text[:200]
    current_app.logger.warning(
        "Shippo track creation error (%s): %s",
        response.status_code,
        message,
    )
    if errors is not None:
        errors.append(f"{tracking_number}: unable to start tracking ({message})")
    return None


def _fetch_track(
    tracking_number: str,
    carrier: Optional[str],
    headers: Dict[str, str],
    errors: Optional[List[str]] = None,
) -> Optional[dict]:
    slug = carrier or ""
    url = f"{API_BASE_URL}/tracks/{slug}/{tracking_number}" if slug else ""

    try:
        if url:
            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code == 404:
                _create_track(tracking_number, carrier, headers, errors)
                response = requests.get(url, headers=headers, timeout=15)
        else:
            created = _create_track(tracking_number, None, headers, errors)
            if created and created.get("carrier"):
                carrier_slug = created["carrier"]
                url = f"{API_BASE_URL}/tracks/{carrier_slug}/{tracking_number}"
                response = requests.get(url, headers=headers, timeout=15)
            else:
                response = None
    except requests.RequestException as exc:
        current_app.logger.warning("Shippo track fetch failed: %s", exc)
        if errors is not None:
            errors.append(f"{tracking_number}: network error ({exc})")
        return None

    if response is None:
        return None

    if response.ok:
        try:
            return response.json()
        except ValueError:
            return None

    message = response.text[:200]
    current_app.logger.warning(
        "Shippo track fetch error (%s): %s",
        response.status_code,
        message,
    )
    if errors is not None:
        errors.append(f"{tracking_number}: unable to fetch tracking ({message})")
    return None


def _select_badge(status_code: str) -> Dict[str, str]:
    return BADGE_STYLES.get(status_code, BADGE_STYLES["unknown"])


def _location_to_string(location: Optional[dict]) -> Optional[str]:
    if not isinstance(location, dict):
        return None
    parts = [
        location.get("city"),
        location.get("state"),
        location.get("zip"),
    ]
    parts = [p for p in parts if p]
    if location.get("country"):
        parts.append(location["country"])
    return ", ".join(parts) if parts else None


def _default_status(fulfillment_state: Optional[str]) -> str:
    if fulfillment_state == "delivered":
        return "delivered"
    if fulfillment_state == "shipped":
        return "in_transit"
    return "unknown"


def _default_status_date(order, status_code: str) -> Optional[datetime]:
    if status_code == "delivered":
        return getattr(order, "delivered_at", None) or getattr(order, "shipped_at", None)
    return getattr(order, "shipped_at", None)


def _apply_shippo_status(order, shippo_payload: dict) -> None:
    tracking_status = (shippo_payload or {}).get("tracking_status") or {}
    raw_status = tracking_status.get("status")
    normalized = STATUS_NORMALIZATION.get(
        (raw_status or "").upper(), order.tracking_status
    )

    order.tracking_status = normalized
    badge = _select_badge(normalized)
    order.tracking_status_label = badge["label"]
    order.tracking_badge_bg = badge["bg"]
    order.tracking_badge_fg = badge["fg"]

    order.tracking_status_raw = raw_status
    order.tracking_status_details = tracking_status.get("status_details")
    order.tracking_status_date = parse_iso_datetime(
        tracking_status.get("status_date")
    ) or order.tracking_status_date
    order.tracking_last_location = _location_to_string(
        tracking_status.get("location")
    )

    order.tracking_est_delivery = parse_iso_datetime(
        shippo_payload.get("eta") or shippo_payload.get("estimated_delivery_date")
    )
    order.shippo_carrier = shippo_payload.get("carrier") or order.shippo_carrier
    order.tracking_url = (
        shippo_payload.get("tracking_url_provider")
        or shippo_payload.get("tracking_url_local")
        or order.tracking_url
    )


def annotate_orders_with_shippo(orders: Sequence) -> Dict[str, object]:
    """
    Enrich order objects with Shippo tracking information (in place).

    Returns a dictionary describing whether Shippo tracking was applied and any
    errors encountered.
    """
    api_key = current_app.config.get("SHIPPO_API_KEY")
    result = {"enabled": bool(api_key), "errors": []}

    if not api_key:
        for order in orders:
        order.tracking_status = _default_status(
            getattr(order, "fulfillment_state", None)
        )
        badge = _select_badge(order.tracking_status)
        order.tracking_status_label = badge["label"]
        order.tracking_badge_bg = badge["bg"]
        order.tracking_badge_fg = badge["fg"]
        order.tracking_status_date = _default_status_date(order, order.tracking_status)
        order.tracking_status_details = None
        order.tracking_last_location = None
        order.tracking_est_delivery = None
        order.tracking_url = None
        return result

    headers = {
        "Authorization": f"ShippoToken {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    # Track once per unique tracking number
    tracking_requests: Dict[str, List[Optional[str]]] = {}
    for order in orders:
        tracking_number = (getattr(order, "tracking_number", "") or "").strip()
        order.tracking_status = _default_status(
            getattr(order, "fulfillment_state", None)
        )
        badge = _select_badge(order.tracking_status)
        order.tracking_status_label = badge["label"]
        order.tracking_badge_bg = badge["bg"]
        order.tracking_badge_fg = badge["fg"]
        order.tracking_status_details = None
        order.tracking_status_date = _default_status_date(order, order.tracking_status)
        order.tracking_last_location = None
        order.tracking_est_delivery = None
        order.tracking_url = None
        order.shippo_carrier = normalize_carrier(getattr(order, "carrier", None))

        if not tracking_number:
            order.tracking_status = "missing"
            badge = _select_badge("missing")
            order.tracking_status_label = badge["label"]
            order.tracking_badge_bg = badge["bg"]
            order.tracking_badge_fg = badge["fg"]
            continue

        carriers = tracking_requests.setdefault(tracking_number, [])
        if order.shippo_carrier not in carriers:
            carriers.append(order.shippo_carrier)

    cache: Dict[Tuple[str, Optional[str]], dict] = {}

    for tracking_number, carrier_candidates in tracking_requests.items():
        candidates: List[Optional[str]] = [
            carrier for carrier in carrier_candidates if carrier
        ]
        if None in carrier_candidates or not candidates:
            candidates.append(None)

        seen: set = set()
        ordered_candidates = [
            carrier for carrier in candidates if not (carrier in seen or seen.add(carrier))
        ]

        for carrier in ordered_candidates:
            payload = _fetch_track(
                tracking_number,
                carrier,
                headers,
                result["errors"],
            )
            if payload:
                key = (tracking_number, payload.get("carrier") or carrier)
                cache[key] = payload
                break

    for order in orders:
        tracking_number = (getattr(order, "tracking_number", "") or "").strip()
        if not tracking_number:
            continue

        carrier_key = order.shippo_carrier
        payload = cache.get((tracking_number, carrier_key))
        if payload is None:
            # Fallback to any payload that matches the tracking number
            payload = next(
                (value for (number, _), value in cache.items() if number == tracking_number),
                None,
            )

        if payload:
            _apply_shippo_status(order, payload)

    return result
