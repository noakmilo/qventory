from flask import (
    render_template, request, redirect, url_for, send_file, flash, Response,
    jsonify, send_from_directory, make_response, current_app
)
from flask_login import login_required, current_user
from sqlalchemy import func, or_
import math
import io
import re
import os
import sys
import base64
import time
import requests
from urllib.parse import urlparse, parse_qs
import csv
from datetime import datetime, date
import hashlib


# Dotenv: carga credenciales/vars desde /opt/qventory/qventory/.env
from dotenv import load_dotenv
load_dotenv("/opt/qventory/qventory/.env")

# >>> IMPRESIÓN (lo existente + QR)
import tempfile
import subprocess
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
import qrcode
# <<<

from ..extensions import db
from ..models.item import Item
from ..models.setting import Setting
from ..models.user import User
from ..helpers import (
    get_or_create_settings, generate_sku, compose_location_code,
    parse_location_code, parse_values, human_from_code, qr_label_image
)
from . import main_bp
from ..helpers.inventory_queries import (
    fetch_active_items,
    fetch_sold_items,
    fetch_ended_items,
    fetch_fulfillment_orders,
    fetch_fulfillment_in_transit,
    fetch_fulfillment_delivered,
    detect_thumbnail_mismatches,
    detect_sale_title_mismatches,
)

PAGE_SIZES = [10, 20, 50, 100, 500]

# ==================== Cloudinary ====================
# pip install cloudinary
CLOUDINARY_CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME")
CLOUDINARY_API_KEY = os.environ.get("CLOUDINARY_API_KEY")
CLOUDINARY_API_SECRET = os.environ.get("CLOUDINARY_API_SECRET")
CLOUDINARY_UPLOAD_FOLDER = os.environ.get("CLOUDINARY_UPLOAD_FOLDER", "qventory/items")
EBAY_VERIFICATION_TOKEN = os.environ.get("EBAY_VERIFICATION_TOKEN", "")
EBAY_DELETIONS_ENDPOINT_URL = os.environ.get("EBAY_DELETIONS_ENDPOINT_URL", "")


cloudinary_enabled = bool(CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET)

if cloudinary_enabled:
    try:
        import cloudinary
        import cloudinary.uploader
        cloudinary.config(
            cloud_name=CLOUDINARY_CLOUD_NAME,
            api_key=CLOUDINARY_API_KEY,
            api_secret=CLOUDINARY_API_SECRET,
            secure=True
        )
    except Exception as _e:
        cloudinary_enabled = False


# ---------------------- Landing pública ----------------------

@main_bp.route("/")
def landing():
    return render_template("landing.html")


# ---------------------- Dashboard (protegido) ----------------------

def _normalize_arg(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _get_inventory_filter_params():
    return {
        "search": _normalize_arg(request.args.get("q")),
        "A": _normalize_arg(request.args.get("A")),
        "B": _normalize_arg(request.args.get("B")),
        "S": _normalize_arg(request.args.get("S")),
        "C": _normalize_arg(request.args.get("C")),
        "platform": _normalize_arg(request.args.get("platform")),
        "missing_data": _normalize_arg(request.args.get("missing_data")),
    }


def _get_pagination_params(default_per_page: int = 20):
    try:
        page = int(request.args.get("page", 1))
    except (TypeError, ValueError):
        page = 1
    page = max(page, 1)

    try:
        per_page = int(request.args.get("per_page", default_per_page))
    except (TypeError, ValueError):
        per_page = default_per_page
    if per_page not in PAGE_SIZES:
        per_page = default_per_page

    offset = (page - 1) * per_page
    return page, per_page, offset


def _build_pagination_metadata(total_items: int, page: int, per_page: int):
    total_pages = max(1, math.ceil(total_items / per_page)) if total_items else 1
    page = max(1, min(page, total_pages))

    base_params = request.args.to_dict(flat=True)
    base_view_args = dict(request.view_args or {})

    def build_url(page_value: int | None = None, per_page_value: int | None = None):
        params = dict(base_view_args)
        params.update(base_params)
        if page_value is not None:
            params["page"] = page_value
        else:
            params.pop("page", None)
        params["per_page"] = per_page_value if per_page_value is not None else per_page
        return url_for(request.endpoint, **params)

    page_links = []
    if total_pages <= 7:
        numbers = list(range(1, total_pages + 1))
    else:
        numbers = [1]
        left = max(2, page - 2)
        right = min(total_pages - 1, page + 2)
        if left > 2:
            numbers.append(None)
        numbers.extend(range(left, right + 1))
        if right < total_pages - 1:
            numbers.append(None)
        numbers.append(total_pages)

    for num in numbers:
        if num is None:
            page_links.append({"ellipsis": True})
        else:
            page_links.append({
                "number": num,
                "url": build_url(page_value=num),
                "active": num == page
            })

    per_page_links = [
        {
            "value": size,
            "url": build_url(page_value=1, per_page_value=size),
            "active": size == per_page
        } for size in PAGE_SIZES
    ]

    start_index = ((page - 1) * per_page + 1) if total_items else 0
    end_index = min(start_index + per_page - 1, total_items) if total_items else 0

    return {
        "page": page,
        "per_page": per_page,
        "total_items": total_items,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "prev_url": build_url(page_value=page - 1) if page > 1 else None,
        "next_url": build_url(page_value=page + 1) if page < total_pages else None,
        "page_links": page_links,
        "per_page_links": per_page_links,
        "start_index": start_index,
        "end_index": end_index,
    }


def _build_independent_pagination(total_items: int, page: int, per_page: int, page_param: str, per_page_param: str):
    """Build pagination metadata for independent tables with custom param names"""
    total_pages = max(1, math.ceil(total_items / per_page)) if total_items else 1
    page = max(1, min(page, total_pages))

    base_params = request.args.to_dict(flat=True)
    base_view_args = dict(request.view_args or {})

    def build_url(page_value: int | None = None, per_page_value: int | None = None):
        params = dict(base_view_args)
        params.update(base_params)
        if page_value is not None:
            params[page_param] = page_value
        else:
            params.pop(page_param, None)
        params[per_page_param] = per_page_value if per_page_value is not None else per_page
        return url_for(request.endpoint, **params)

    page_links = []
    if total_pages <= 7:
        numbers = list(range(1, total_pages + 1))
    else:
        numbers = [1]
        left = max(2, page - 2)
        right = min(total_pages - 1, page + 2)
        if left > 2:
            numbers.append(None)
        numbers.extend(range(left, right + 1))
        if right < total_pages - 1:
            numbers.append(None)
        numbers.append(total_pages)

    for num in numbers:
        if num is None:
            page_links.append({"ellipsis": True})
        else:
            page_links.append({
                "number": num,
                "url": build_url(page_value=num),
                "active": num == page
            })

    per_page_links = [
        {
            "value": size,
            "url": build_url(page_value=1, per_page_value=size),
            "active": size == per_page
        } for size in PAGE_SIZES
    ]

    start_index = ((page - 1) * per_page + 1) if total_items else 0
    end_index = min(start_index + per_page - 1, total_items) if total_items else 0

    return {
        "page": page,
        "per_page": per_page,
        "total_items": total_items,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "prev_url": build_url(page_value=page - 1) if page > 1 else None,
        "next_url": build_url(page_value=page + 1) if page < total_pages else None,
        "page_links": page_links,
        "per_page_links": per_page_links,
        "start_index": start_index,
        "end_index": end_index,
        "page_param": page_param,
        "per_page_param": per_page_param,
    }


@main_bp.route("/api/items/<int:item_id>/inline", methods=["PATCH"])
@login_required
def api_update_item_inline(item_id):
    item = Item.query.filter_by(id=item_id, user_id=current_user.id).first()
    if not item:
        return jsonify({"ok": False, "error": "Item not found"}), 404

    data = request.get_json(silent=True) or {}
    field = (data.get("field") or "").strip()

    if not field:
        return jsonify({"ok": False, "error": "Missing field parameter"}), 400

    try:
        if field == "supplier":
            value = (data.get("value") or "").strip()
            item.supplier = value or None
        elif field == "item_cost":
            raw_value = data.get("value")
            if raw_value in (None, ""):
                item.item_cost = None
            else:
                try:
                    cost = float(raw_value)
                except (TypeError, ValueError):
                    return jsonify({"ok": False, "error": "Invalid cost value"}), 400
                if cost < 0:
                    return jsonify({"ok": False, "error": "Cost cannot be negative"}), 400
                item.item_cost = cost

            # IMPORTANT: If this item has been sold, update the Sale record too
            # This ensures analytics profit calculations remain accurate
            from qventory.models.sale import Sale
            sales = Sale.query.filter_by(item_id=item.id, user_id=current_user.id).all()
            for sale in sales:
                sale.item_cost = item.item_cost
                sale.calculate_profit()  # Recalculate gross_profit and net_profit
        elif field == "location":
            components = data.get("components") or {}
            settings = get_or_create_settings(current_user)

            def clean(value):
                if value is None:
                    return None
                value = str(value).strip()
                return value or None

            A = clean(components.get("A")) if settings.enable_A else None
            B = clean(components.get("B")) if settings.enable_B else None
            S = clean(components.get("S")) if settings.enable_S else None
            C = clean(components.get("C")) if settings.enable_C else None

            enabled = tuple(settings.enabled_levels())
            location_code = compose_location_code(A=A, B=B, S=S, C=C, enabled=enabled)

            if settings.enable_A:
                item.A = A
            if settings.enable_B:
                item.B = B
            if settings.enable_S:
                item.S = S
            if settings.enable_C:
                item.C = C

            if not settings.enable_A:
                item.A = None
            if not settings.enable_B:
                item.B = None
            if not settings.enable_S:
                item.S = None
            if not settings.enable_C:
                item.C = None

            item.location_code = location_code or None
        else:
            return jsonify({"ok": False, "error": "Field not supported"}), 400

        item.updated_at = datetime.utcnow()
        db.session.commit()

        # Return updated item data instead of full row HTML to prevent losing unsaved edits
        response_data = {
            "ok": True,
            "field": field,
            "item_id": item.id
        }

        # Return field-specific data
        if field == "supplier":
            response_data["supplier"] = item.supplier
        elif field == "item_cost":
            response_data["item_cost"] = item.item_cost
        elif field == "location":
            response_data["location_code"] = item.location_code
            response_data["A"] = item.A
            response_data["B"] = item.B
            response_data["S"] = item.S
            response_data["C"] = item.C

        return jsonify(response_data)
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("Inline update failed")
        return jsonify({"ok": False, "error": str(exc)}), 500


@main_bp.route("/api/inventory/count")
@login_required
def inventory_count():
    """
    Simple endpoint to get current inventory count
    Used for polling instead of SSE (more reliable, no connection issues)
    """
    from sqlalchemy import text

    try:
        result = db.session.execute(
            text("SELECT COUNT(*) FROM items WHERE user_id = :user_id AND is_active = true"),
            {"user_id": current_user.id}
        )
        count = result.scalar()
        return jsonify({"count": count})
    except Exception as e:
        current_app.logger.error(f"Error getting inventory count: {str(e)}")
        return jsonify({"error": "Failed to get count"}), 500


@main_bp.route("/api/inventory/stream")
@login_required
def inventory_stream():
    """
    Server-Sent Events stream for inventory updates
    DEPRECATED: Causes database "idle in transaction" issues
    Use /api/inventory/count with polling instead
    """
    # IMPORTANT: Capture user_id AND app BEFORE entering the generator
    # current_user and current_app are only available in the request context
    user_id = current_user.id
    app = current_app._get_current_object()

    def generate(uid, flask_app):
        import json
        from sqlalchemy import text

        # Use the captured Flask app to create context
        with flask_app.app_context():
            try:
                # Send initial count - use efficient SQL query instead of ORM .count()
                result = db.session.execute(
                    text("SELECT COUNT(*) FROM items WHERE user_id = :user_id AND is_active = true"),
                    {"user_id": uid}
                )
                initial_count = result.scalar()
            finally:
                db.session.remove()  # Completely close session to avoid idle in transaction

            yield f"data: {json.dumps({'count': initial_count, 'type': 'initial'})}\n\n"

            # Keep connection alive and check for changes every 5 seconds
            last_count = initial_count
            while True:
                try:
                    time.sleep(5)

                    # Use efficient SQL query with fresh session each time
                    try:
                        result = db.session.execute(
                            text("SELECT COUNT(*) FROM items WHERE user_id = :user_id AND is_active = true"),
                            {"user_id": uid}
                        )
                        current_count = result.scalar()
                    finally:
                        db.session.remove()  # Completely close session to avoid idle in transaction

                    if current_count != last_count:
                        yield f"data: {json.dumps({'count': current_count, 'type': 'update'})}\n\n"
                        last_count = current_count
                    else:
                        # Send heartbeat to keep connection alive
                        yield f": heartbeat\n\n"

                except Exception as e:
                    flask_app.logger.error(f"SSE error: {str(e)}")
                    break

    return Response(generate(user_id, app), mimetype='text/event-stream')


@main_bp.route("/api/items/recent")
@login_required
def api_recent_items():
    """
    API endpoint to fetch recent items for dynamic table refresh
    Returns HTML rows for items created/updated after a given timestamp
    """
    from datetime import datetime

    # Get timestamp parameter (ISO format)
    since = request.args.get('since', None)

    if not since:
        return jsonify({"ok": False, "error": "Missing 'since' parameter"}), 400

    try:
        since_dt = datetime.fromisoformat(since.replace('Z', '+00:00'))
    except ValueError:
        return jsonify({"ok": False, "error": "Invalid timestamp format"}), 400

    # Fetch items created or updated after the timestamp
    items = Item.query.filter(
        Item.user_id == current_user.id,
        Item.is_active == True,
        db.or_(
            Item.created_at > since_dt,
            Item.updated_at > since_dt
        )
    ).order_by(Item.created_at.desc()).all()

    if not items:
        return jsonify({"ok": True, "count": 0, "html": ""})

    # Get user settings for location labels
    from ..models.setting import Setting as UserSettings
    settings = UserSettings.query.filter_by(user_id=current_user.id).first()
    if not settings:
        settings = UserSettings(user_id=current_user.id)

    # Render each item row
    rows_html = []
    for item in items:
        row_html = render_template('_item_row.html',
                                   item=item,
                                   it=item,
                                   view_type='active',
                                   settings=settings,
                                   current_user=current_user)
        rows_html.append(row_html)

    return jsonify({
        "ok": True,
        "count": len(items),
        "html": "\n".join(rows_html),
        "item_ids": [item.id for item in items]
    })


@main_bp.route("/api/suppliers/search", methods=["GET"])
@login_required
def api_search_suppliers():
    """
    Search existing suppliers with autocomplete
    Query params: q (search query)
    Returns: JSON array of unique supplier names
    """
    query = request.args.get('q', '').strip()

    # Return empty if no query (but accept single character queries)
    if not query:
        return jsonify([])

    # Search for suppliers matching the query (case-insensitive, starts from 1 character)
    suppliers = db.session.query(Item.supplier).filter(
        Item.user_id == current_user.id,
        Item.supplier.isnot(None),
        Item.supplier != '',
        Item.supplier.ilike(f'%{query}%')
    ).distinct().order_by(Item.supplier.asc()).limit(10).all()

    # Extract supplier names from result tuples
    supplier_list = [s[0] for s in suppliers]

    return jsonify(supplier_list)


@main_bp.route("/dashboard")
@login_required
def dashboard():
    """Dashboard home with stats, recent activity, and pending tasks"""
    from qventory.helpers.dashboard_queries import (
        fetch_dashboard_stats,
        fetch_recent_sales,
        fetch_recently_listed,
        fetch_recently_sold_items,
        fetch_recent_fulfillment,
        fetch_pending_tasks
    )

    s = get_or_create_settings(current_user)

    # Fetch all dashboard data
    stats = fetch_dashboard_stats(db.session, user_id=current_user.id)
    recent_sales = fetch_recent_sales(db.session, user_id=current_user.id, limit=5)
    recently_listed = fetch_recently_listed(db.session, user_id=current_user.id, limit=5)
    recently_sold = fetch_recently_sold_items(db.session, user_id=current_user.id, limit=5)
    recent_fulfillment = fetch_recent_fulfillment(db.session, user_id=current_user.id, limit=10)
    pending_tasks = fetch_pending_tasks(db.session, user_id=current_user.id)

    # Plan usage info
    plan_limits = current_user.get_plan_limits()
    items_remaining = current_user.items_remaining()
    plan_max_items = getattr(plan_limits, "max_items", None) if plan_limits else None
    upgrade_threshold = current_app.config.get("DASHBOARD_UPGRADE_THRESHOLD", 10)
    upgrade_recommendation = (
        plan_max_items is not None
        and items_remaining is not None
        and items_remaining <= upgrade_threshold
    )

    # Attach plan metadata to pending tasks namespace for template access
    setattr(pending_tasks, "upgrade_recommendation", upgrade_recommendation)
    setattr(pending_tasks, "items_remaining", items_remaining)
    setattr(pending_tasks, "plan_max_items", plan_max_items)
    setattr(pending_tasks, "upgrade_threshold", upgrade_threshold)

    # Calculate today's listings for motivational message
    from datetime import datetime
    from qventory.models.item import Item
    # Count items CREATED today (added to Qventory today), not listing_date
    # listing_date is when they were published on eBay (could be old)
    # created_at is when they were added to Qventory (the action we want to reward)
    # Using UTC midnight as the cutoff since created_at is stored in UTC
    today_start_utc = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_listings_count = Item.query.filter(
        Item.user_id == current_user.id,
        Item.created_at >= today_start_utc
    ).count()

    return render_template(
        "dashboard_home.html",
        settings=s,
        stats=stats,
        recent_sales=recent_sales,
        recently_listed=recently_listed,
        recently_sold=recently_sold,
        recent_fulfillment=recent_fulfillment,
        pending_tasks=pending_tasks,
        items_remaining=items_remaining,
        plan_max_items=plan_max_items,
        upgrade_task_dismiss_key=f"upgrade_task_dismissed_{current_user.id}",
        upgrade_banner_dismiss_key=f"upgrade_banner_dismissed_{current_user.id}",
        today_listings_count=today_listings_count
    )


@main_bp.route("/upgrade")
@login_required
def upgrade():
    """Show upgrade page with plan comparison (non-functional placeholder)"""
    from qventory.models.subscription import PlanLimit

    # Get all plan limits
    plans = PlanLimit.query.filter(
        ~PlanLimit.plan.in_(["early_adopter", "god"])
    ).order_by(
        db.case(
            (PlanLimit.plan == 'free', 1),
            (PlanLimit.plan == 'premium', 2),
            (PlanLimit.plan == 'pro', 3),
            else_=99
        )
    ).all()

    # Get current user's plan info
    subscription = current_user.get_subscription()
    current_plan_limits = current_user.get_plan_limits()
    items_remaining = current_user.items_remaining()

    return render_template(
        "upgrade.html",
        plans=plans,
        current_plan=current_plan_limits,
        current_user_plan=subscription.plan if subscription else None,
        items_remaining=items_remaining
    )


# ---------------------- Inventory Views ----------------------

@main_bp.route("/inventory/active")
@login_required
def inventory_active():
    """Show only active items (is_active=True)"""
    s = get_or_create_settings(current_user)

    page, per_page, offset = _get_pagination_params()
    filters = _get_inventory_filter_params()
    items, total_items = fetch_active_items(
        db.session,
        user_id=current_user.id,
        limit=per_page,
        offset=offset,
        **filters,
    )

    if total_items and offset >= total_items and page > 1:
        total_pages = max(1, math.ceil(total_items / per_page))
        page = total_pages
        offset = (page - 1) * per_page
        items, total_items = fetch_active_items(
            db.session,
            user_id=current_user.id,
            limit=per_page,
            offset=offset,
            **filters,
        )

    pagination = _build_pagination_metadata(total_items, page, per_page)

    mismatches = detect_thumbnail_mismatches(db.session, user_id=current_user.id)
    if mismatches:
        sample = mismatches[:3]
        current_app.logger.warning(
            "Thumbnail slug collisions detected for user %s: %s",
            current_user.id,
            sample,
        )

    def distinct(col):
        return [
            r[0] for r in db.session.query(col)
            .filter(col.isnot(None), Item.user_id == current_user.id)
            .distinct().order_by(col.asc()).all()
        ]

    options = {
        "A": distinct(Item.A) if s.enable_A else [],
        "B": distinct(Item.B) if s.enable_B else [],
        "S": distinct(Item.S) if s.enable_S else [],
        "C": distinct(Item.C) if s.enable_C else [],
    }

    plan_limits = current_user.get_plan_limits()
    items_remaining = current_user.items_remaining()
    plan_max_items = getattr(plan_limits, "max_items", None) if plan_limits else None
    show_upgrade_banner = (
        plan_max_items is not None
        and items_remaining is not None
        and items_remaining <= 0
    )

    return render_template(
        "inventory_list.html",
        items=items,
        settings=s,
        options=options,
        total_items=total_items,
        pagination=pagination,
        view_type="active",
        page_title="Active Inventory",
        items_remaining=items_remaining,
        plan_max_items=plan_max_items,
        show_upgrade_banner=show_upgrade_banner,
        upgrade_banner_dismiss_key=f"upgrade_banner_dismissed_{current_user.id}"
    )


@main_bp.route("/inventory/sold")
@login_required
def inventory_sold():
    """Show items that have been sold (have sales records)"""
    s = get_or_create_settings(current_user)

    page, per_page, offset = _get_pagination_params()
    filters = _get_inventory_filter_params()
    items, total_items = fetch_sold_items(
        db.session,
        user_id=current_user.id,
        limit=per_page,
        offset=offset,
        **filters,
    )

    if total_items and offset >= total_items and page > 1:
        total_pages = max(1, math.ceil(total_items / per_page))
        page = total_pages
        offset = (page - 1) * per_page
        items, total_items = fetch_sold_items(
            db.session,
            user_id=current_user.id,
            limit=per_page,
            offset=offset,
            **filters,
        )

    pagination = _build_pagination_metadata(total_items, page, per_page)

    # FIXME: This query is causing severe performance issues (4+ minute timeouts)
    # Commenting out until we can optimize it or add proper indexes
    # sale_title_mismatches = detect_sale_title_mismatches(db.session, user_id=current_user.id)
    # if sale_title_mismatches:
    #     current_app.logger.warning(
    #         "Sale title mismatches detected for user %s (sample of %d)",
    #         current_user.id,
    #         len(sale_title_mismatches),
    #     )

    # FIXME: These distinct queries scan the entire items table and are very slow
    # Sold items view doesn't need these filter options - disabling for performance
    # def distinct(col):
    #     return [
    #         r[0] for r in db.session.query(col)
    #         .filter(col.isnot(None), Item.user_id == current_user.id)
    #         .distinct().order_by(col.asc()).all()
    #     ]

    options = {
        "A": [],  # distinct(Item.A) if s.enable_A else [],
        "B": [],  # distinct(Item.B) if s.enable_B else [],
        "S": [],  # distinct(Item.S) if s.enable_S else [],
        "C": [],  # distinct(Item.C) if s.enable_C else [],
    }

    # Sold items view doesn't need plan limits (items are already sold)
    # Skip expensive items_remaining() calculation
    plan_limits = None
    items_remaining = None
    plan_max_items = None

    return render_template(
        "inventory_list.html",
        items=items,
        settings=s,
        options=options,
        total_items=total_items,
        pagination=pagination,
        view_type="sold",
        page_title="Sold Items",
        items_remaining=items_remaining,
        plan_max_items=plan_max_items,
        show_upgrade_banner=False,
        upgrade_banner_dismiss_key=f"upgrade_banner_dismissed_{current_user.id}"
    )


# COMMENTED OUT - Not critical, items moved to soft delete approach
# @main_bp.route("/inventory/ended")
# @login_required
# def inventory_ended():
#     """Show inactive/ended items (is_active=False)"""
#     s = get_or_create_settings(current_user)
#
#     page, per_page, offset = _get_pagination_params()
#     filters = _get_inventory_filter_params()
#     items, total_items = fetch_ended_items(
#         db.session,
#         user_id=current_user.id,
#         limit=per_page,
#         offset=offset,
#         **filters,
#     )
#
#     if total_items and offset >= total_items and page > 1:
#         total_pages = max(1, math.ceil(total_items / per_page))
#         page = total_pages
#         offset = (page - 1) * per_page
#         items, total_items = fetch_ended_items(
#             db.session,
#             user_id=current_user.id,
#             limit=per_page,
#             offset=offset,
#             **filters,
#         )
#
#     pagination = _build_pagination_metadata(total_items, page, per_page)
#
#     mismatches = detect_thumbnail_mismatches(db.session, user_id=current_user.id)
#     if mismatches:
#         sample = mismatches[:3]
#         current_app.logger.warning(
#             "Thumbnail slug collisions detected for ended items user %s: %s",
#             current_user.id,
#             sample,
#         )
#
#     def distinct(col):
#         return [
#             r[0] for r in db.session.query(col)
#             .filter(col.isnot(None), Item.user_id == current_user.id)
#             .distinct().order_by(col.asc()).all()
#         ]
#
#     options = {
#         "A": distinct(Item.A) if s.enable_A else [],
#         "B": distinct(Item.B) if s.enable_B else [],
#         "S": distinct(Item.S) if s.enable_S else [],
#         "C": distinct(Item.C) if s.enable_C else [],
#     }
#
#     plan_limits = current_user.get_plan_limits()
#     items_remaining = current_user.items_remaining()
#     plan_max_items = getattr(plan_limits, "max_items", None) if plan_limits else None
#
#     return render_template(
#         "inventory_list.html",
#         items=items,
#         settings=s,
#         options=options,
#         total_items=total_items,
#         pagination=pagination,
#         view_type="ended",
#         page_title="Ended Inventory",
#         items_remaining=items_remaining,
#         plan_max_items=plan_max_items,
#         show_upgrade_banner=False,
#         upgrade_banner_dismiss_key=f"upgrade_banner_dismissed_{current_user.id}"
#     )


# ---------------------- Fulfillment View ----------------------

@main_bp.route("/fulfillment")
@login_required
def fulfillment():
    """Show shipped and delivered orders with independent pagination"""
    from ..models.sale import Sale

    # Get pagination params for "in transit" table
    try:
        transit_page = int(request.args.get("transit_page", 1))
    except (TypeError, ValueError):
        transit_page = 1
    transit_page = max(transit_page, 1)

    try:
        transit_per_page = int(request.args.get("transit_per_page", 20))
    except (TypeError, ValueError):
        transit_per_page = 20
    if transit_per_page not in PAGE_SIZES:
        transit_per_page = 20
    transit_offset = (transit_page - 1) * transit_per_page

    # Get pagination params for "delivered" table
    try:
        delivered_page = int(request.args.get("delivered_page", 1))
    except (TypeError, ValueError):
        delivered_page = 1
    delivered_page = max(delivered_page, 1)

    try:
        delivered_per_page = int(request.args.get("delivered_per_page", 20))
    except (TypeError, ValueError):
        delivered_per_page = 20
    if delivered_per_page not in PAGE_SIZES:
        delivered_per_page = 20
    delivered_offset = (delivered_page - 1) * delivered_per_page

    # Fetch in transit orders (shipped but not delivered)
    shipped_orders, shipped_total = fetch_fulfillment_in_transit(
        db.session,
        user_id=current_user.id,
        limit=transit_per_page,
        offset=transit_offset,
    )

    # Fetch delivered orders
    delivered_orders, delivered_total = fetch_fulfillment_delivered(
        db.session,
        user_id=current_user.id,
        limit=delivered_per_page,
        offset=delivered_offset,
    )

    # Resolve titles and SKUs
    for order in shipped_orders:
        if getattr(order, "resolved_title", None):
            order.item_title = order.resolved_title
        if getattr(order, "resolved_sku", None):
            order.item_sku = order.resolved_sku

    for order in delivered_orders:
        if getattr(order, "resolved_title", None):
            order.item_title = order.resolved_title
        if getattr(order, "resolved_sku", None):
            order.item_sku = order.resolved_sku

    # Build independent pagination for in transit table
    transit_pagination = _build_independent_pagination(
        total_items=shipped_total,
        page=transit_page,
        per_page=transit_per_page,
        page_param="transit_page",
        per_page_param="transit_per_page",
    )

    # Build independent pagination for delivered table
    delivered_pagination = _build_independent_pagination(
        total_items=delivered_total,
        page=delivered_page,
        per_page=delivered_per_page,
        page_param="delivered_page",
        per_page_param="delivered_per_page",
    )

    # Calculate total value across all fulfilled orders
    total_value = db.session.query(func.coalesce(func.sum(Sale.sold_price), 0)).filter(
        Sale.user_id == current_user.id,
        or_(Sale.shipped_at.isnot(None), Sale.delivered_at.isnot(None))
    ).scalar()

    return render_template(
        "fulfillment.html",
        shipped_orders=shipped_orders,
        delivered_orders=delivered_orders,
        shipped_count=shipped_total,
        delivered_count=delivered_total,
        total_value=total_value or 0,
        transit_pagination=transit_pagination,
        delivered_pagination=delivered_pagination,
        shippo_enabled=False,
        shippo_errors=[],
        shippo_last_update=None,
    )


@main_bp.route("/fulfillment/debug-parse", methods=["GET"])
@login_required
def debug_parse_order():
    """Debug: Test parse_ebay_order_to_sale function"""
    from ..helpers.ebay_inventory import fetch_ebay_orders, parse_ebay_order_to_sale

    result = fetch_ebay_orders(current_user.id, filter_status='FULFILLED', limit=3)

    if not result['success']:
        return jsonify({
            'success': False,
            'error': result.get('error')
        })

    parsed_orders = []
    for order_data in result['orders'][:3]:
        sale_data = parse_ebay_order_to_sale(order_data, user_id=current_user.id)
        parsed_orders.append({
            'order_id': order_data.get('orderId'),
            'orderFulfillmentStatus': order_data.get('orderFulfillmentStatus'),
            'parsed_sale_data': sale_data
        })

    return jsonify({
        'success': True,
        'orders': parsed_orders
    })


@main_bp.route("/fulfillment/debug-db", methods=["GET"])
@login_required
def debug_database_sales():
    """Debug: Show raw database values for sales"""
    from ..models.sale import Sale

    sales = Sale.query.filter_by(user_id=current_user.id).order_by(Sale.id.desc()).limit(10).all()

    debug_data = []
    for sale in sales:
        debug_data.append({
            'id': sale.id,
            'marketplace_order_id': sale.marketplace_order_id,
            'status': sale.status,
            'shipped_at': str(sale.shipped_at) if sale.shipped_at else None,
            'delivered_at': str(sale.delivered_at) if sale.delivered_at else None,
            'tracking_number': sale.tracking_number,
            'carrier': sale.carrier,
            'sold_at': str(sale.sold_at) if sale.sold_at else None,
        })

    return jsonify({
        'success': True,
        'sales': debug_data,
        'total': len(debug_data)
    })


@main_bp.route("/fulfillment/debug-ebay-connection", methods=["GET"])
@login_required
def debug_ebay_connection():
    """Debug: Test eBay connection and show order info"""
    from ..helpers.ebay_inventory import fetch_ebay_orders, get_user_access_token

    # Check if user has eBay token
    token = get_user_access_token(current_user.id)

    if not token:
        return jsonify({
            'success': False,
            'error': 'No eBay access token found. Please connect your eBay account in Settings.',
            'has_token': False
        })

    # Try to fetch orders
    result = fetch_ebay_orders(current_user.id, filter_status=None, limit=5)

    if result['success']:
        orders = result['orders']
        order_summary = []
        for order in orders[:5]:
            order_summary.append({
                'order_id': order.get('orderId'),
                'status': order.get('orderFulfillmentStatus'),
                'creation_date': order.get('creationDate'),
                'line_items_count': len(order.get('lineItems', []))
            })

        return jsonify({
            'success': True,
            'has_token': True,
            'total_orders': len(orders),
            'orders_sample': order_summary,
            'message': f'Connected! Found {len(orders)} orders'
        })
    else:
        return jsonify({
            'success': False,
            'has_token': True,
            'error': result.get('error', 'Unknown error'),
            'message': 'eBay API returned an error'
        })


@main_bp.route("/fulfillment/debug-order", methods=["GET"])
@login_required
def debug_ebay_order():
    """Debug: Show raw eBay order structure with fulfillment details"""
    from ..helpers.ebay_inventory import fetch_ebay_orders, fetch_shipping_fulfillment_details

    result = fetch_ebay_orders(current_user.id, filter_status='FULFILLED', limit=5)

    if result['success'] and result['orders']:
        debug_orders = []

        for order in result['orders'][:5]:
            order_info = {
                'order_id': order.get('orderId'),
                'order_fulfillment_status': order.get('orderFulfillmentStatus'),
                'creation_date': order.get('creationDate'),
                'last_modified_date': order.get('lastModifiedDate'),
                'fulfillment_hrefs': order.get('fulfillmentHrefs', []),
                'fulfillment_details': []
            }

            # Fetch detailed fulfillment info
            fulfillment_hrefs = order.get('fulfillmentHrefs', [])
            for href in fulfillment_hrefs[:1]:  # Just first one to avoid too many requests
                details = fetch_shipping_fulfillment_details(current_user.id, href)
                if details:
                    order_info['fulfillment_details'].append({
                        'href': href,
                        'shipped_date': details.get('shippedDate'),
                        'line_items': [
                            {
                                'line_item_id': li.get('lineItemId'),
                                'shipment_tracking': li.get('shipmentTracking', {})
                            }
                            for li in details.get('lineItems', [])
                        ]
                    })

            debug_orders.append(order_info)

        return jsonify({
            'success': True,
            'orders': debug_orders,
            'total_orders': len(result['orders'])
        })
    else:
        return jsonify({
            'success': False,
            'error': result.get('error', 'No orders found')
        })


@main_bp.route("/fulfillment/sync-ebay-orders", methods=["POST"])
@login_required
def sync_ebay_orders():
    """Sync orders from eBay Fulfillment API"""
    from ..helpers.ebay_inventory import fetch_ebay_orders, parse_ebay_order_to_sale
    from ..models.sale import Sale

    try:
        # Fetch orders from eBay
        # Get both FULFILLED (delivered) and IN_PROGRESS (in transit) orders
        # Increased limit to 800 to capture all 778 orders
        result = fetch_ebay_orders(current_user.id, filter_status='FULFILLED,IN_PROGRESS', limit=800)

        if not result['success']:
            return jsonify({
                'success': False,
                'error': result['error']
            }), 400

        orders = result['orders']

        if not orders:
            return jsonify({
                'success': True,
                'message': 'No new orders to sync',
                'orders_synced': 0
            })

        # Log unique orderFulfillmentStatus values for debugging
        statuses = set(order.get('orderFulfillmentStatus', 'UNKNOWN') for order in orders)
        print(f"[FULFILLMENT_SYNC] Found {len(orders)} orders with statuses: {statuses}", file=sys.stderr)

        # Process each order
        orders_created = 0
        orders_updated = 0

        for order_data in orders:
            try:
                # Pass user_id to get detailed fulfillment info
                sale_data = parse_ebay_order_to_sale(order_data, user_id=current_user.id)

                if not sale_data:
                    print(f"[FULFILLMENT_SYNC] Failed to parse order {order_data.get('orderId', 'UNKNOWN')}", file=sys.stderr)
                    continue

                # Check if order already exists
                existing_sale = Sale.query.filter_by(
                    user_id=current_user.id,
                    marketplace_order_id=sale_data['marketplace_order_id']
                ).first()

                if existing_sale:
                    # Update existing sale with latest fulfillment data
                    # Always update these fields from eBay, even if None
                    existing_sale.tracking_number = sale_data.get('tracking_number') or existing_sale.tracking_number
                    existing_sale.carrier = sale_data.get('carrier') or existing_sale.carrier
                    existing_sale.shipped_at = sale_data.get('shipped_at') or existing_sale.shipped_at
                    existing_sale.status = sale_data.get('status') or existing_sale.status

                    # CRITICAL: Always update delivered_at from eBay if FULFILLED
                    delivered_value = sale_data.get('delivered_at')
                    if delivered_value:
                        existing_sale.delivered_at = delivered_value
                        print(f"[FULFILLMENT_SYNC] Updated delivered_at for {sale_data['marketplace_order_id']}: {delivered_value}", file=sys.stderr)

                    existing_sale.updated_at = datetime.utcnow()

                    # CRITICAL: Commit immediately after each update to avoid worker conflicts
                    db.session.commit()
                    orders_updated += 1
                else:
                    # Try to match with existing item by SKU
                    item_id = None
                    if sale_data.get('item_sku'):
                        from ..models.item import Item
                        item = Item.query.filter_by(
                            user_id=current_user.id,
                            sku=sale_data['item_sku']
                        ).first()
                        if item:
                            item_id = item.id
                            # Update sale data with item cost if available
                            if item.item_cost:
                                sale_data['item_cost'] = item.item_cost

                    # Create new sale
                    new_sale = Sale(
                        user_id=current_user.id,
                        item_id=item_id,
                        **sale_data
                    )

                    # Calculate profit
                    new_sale.calculate_profit()

                    db.session.add(new_sale)
                    orders_created += 1

            except Exception as e:
                print(f"[FULFILLMENT_SYNC] Error processing order: {str(e)}", file=sys.stderr)
                import traceback
                traceback.print_exc()
                continue

        # Note: Each order is committed immediately in the loop above
        # This prevents worker conflicts with multiple gunicorn processes
        print(f"[FULFILLMENT_SYNC] Completed: {orders_created} created, {orders_updated} updated (committed per-order)", file=sys.stderr)

        return jsonify({
            'success': True,
            'message': f'Synced {orders_created} new and updated {orders_updated} existing orders',
            'orders_synced': orders_created + orders_updated,
            'orders_created': orders_created,
            'orders_updated': orders_updated
        })

    except Exception as e:
        db.session.rollback()
        print(f"[FULFILLMENT_SYNC] Error: {str(e)}", file=sys.stderr)
        return jsonify({
            'success': False,
            'error': f'Sync failed: {str(e)}'
        }), 500


# ---------------------- CSV Export/Import (protegido) ----------------------

@main_bp.route("/export/csv")
@login_required
def export_csv():
    items = Item.query.filter_by(user_id=current_user.id).order_by(Item.created_at.asc()).all()

    output = io.StringIO()
    writer = csv.writer(output)

    headers = [
        'id', 'sku', 'title', 'listing_link',
        'web_url', 'ebay_url', 'amazon_url', 'mercari_url', 'vinted_url', 'poshmark_url', 'depop_url',
        'A', 'B', 'S', 'C', 'location_code',
        # nuevos
        'item_thumb', 'supplier', 'item_cost', 'item_price', 'listing_date',
        'created_at'
    ]
    writer.writerow(headers)

    for it in items:
        row = [
            it.id,
            it.sku,
            it.title,
            it.listing_link or '',
            it.web_url or '',
            it.ebay_url or '',
            it.amazon_url or '',
            it.mercari_url or '',
            it.vinted_url or '',
            it.poshmark_url or '',
            it.depop_url or '',
            it.A or '',
            it.B or '',
            it.S or '',
            it.C or '',
            it.location_code or '',
            it.item_thumb or '',
            it.supplier or '',
            f"{it.item_cost:.2f}" if it.item_cost is not None else '',
            f"{it.item_price:.2f}" if it.item_price is not None else '',
            it.listing_date.strftime('%Y-%m-%d') if isinstance(it.listing_date, (date, datetime)) and it.listing_date else '',
            it.created_at.strftime('%Y-%m-%d %H:%M:%S') if it.created_at else ''
        ]
        writer.writerow(row)

    output.seek(0)
    csv_data = output.getvalue().encode('utf-8')
    output.close()

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"qventory_backup_{current_user.username}_{timestamp}.csv"

    return send_file(
        io.BytesIO(csv_data),
        mimetype='text/csv',
        as_attachment=True,
        download_name=filename
    )


# ===== CSV Import Helpers =====

def _detect_csv_format(fieldnames):
    """
    Detecta el formato del CSV:
    - 'qventory': formato nativo de Qventory (tiene 'sku' y 'title')
    - 'flipwise': formato de Flipwise/otras plataformas (tiene 'Product', 'Cost', 'List price', etc.)
    - 'unknown': formato desconocido
    """
    fieldnames_lower = [f.lower().strip() for f in fieldnames]

    # Formato Qventory: debe tener 'sku' y 'title'
    if 'sku' in fieldnames_lower and 'title' in fieldnames_lower:
        return 'qventory'

    # Formato Flipwise/similar: tiene 'Product' o 'product' y otros campos característicos
    if 'product' in fieldnames_lower:
        return 'flipwise'

    return 'unknown'


def _parse_external_row_to_qventory(row, user_id):
    """
    Convierte una fila de CSV externo (Flipwise, etc.) al formato de Qventory.

    Mapeo de campos:
    - Product -> title
    - Cost -> item_cost
    - List price -> item_price
    - Purchased at -> supplier
    - eBay Item ID -> ebay_url (si existe)
    - Genera SKU automáticamente
    - Usa fecha actual como listing_date
    - Ignora location (usuario lo define después)
    """
    # Helpers
    def fstr(key):
        val = row.get(key, '')
        if isinstance(val, str):
            return val.strip() or None
        return str(val).strip() if val else None

    def ffloat(key):
        val = fstr(key)
        if not val:
            return None
        try:
            return float(val.replace(',', ''))
        except:
            return None

    # Extraer datos del CSV externo
    title = fstr('Product') or fstr('product') or fstr('Title') or fstr('title')
    if not title:
        return None

    # Generar SKU automático usando el helper de Qventory
    sku = generate_sku()

    # Mapear campos
    cost = ffloat('Cost') or ffloat('cost') or ffloat('Item Cost') or ffloat('item_cost')
    price = ffloat('List price') or ffloat('list price') or ffloat('List Price') or ffloat('Price') or ffloat('price')

    # Reconocer múltiples variantes de la columna supplier
    supplier = (
        fstr('Supplier') or fstr('supplier') or
        fstr('Purchased at') or fstr('purchased at') or fstr('Purchased At') or
        fstr('Buy at') or fstr('buy at') or fstr('Buy At') or
        fstr('buy_at') or fstr('Buy_At') or
        fstr('Bought at') or fstr('bought at') or fstr('Bought At') or
        fstr('Vendor') or fstr('vendor') or
        fstr('Source') or fstr('source')
    )

    # eBay Item ID -> construir URL de eBay
    ebay_item_id = fstr('eBay Item ID') or fstr('ebay item id')
    ebay_url = f"https://www.ebay.com/itm/{ebay_item_id}" if ebay_item_id else None

    # Usar fecha actual como listing_date (ignoramos las fechas del CSV externo)
    listing_date = date.today()

    return {
        'sku': sku,
        'title': title,
        'item_cost': cost,
        'item_price': price,
        'supplier': supplier,
        'ebay_url': ebay_url,
        'listing_date': listing_date,
        # Campos que se ignoran (usuario los define después)
        'A': None,
        'B': None,
        'S': None,
        'C': None,
        'location_code': None,
        'listing_link': None,
        'web_url': None,
        'amazon_url': None,
        'mercari_url': None,
        'vinted_url': None,
        'poshmark_url': None,
        'depop_url': None,
        'item_thumb': None
    }


def _parse_qventory_row(row):
    """Parse una fila del formato nativo de Qventory"""
    def fstr(k):
        return (row.get(k) or '').strip() or None

    def ffloat(k):
        v = (row.get(k) or '').strip()
        try:
            return float(v) if v != '' else None
        except:
            return None

    def fdate(k):
        v = (row.get(k) or '').strip()
        if not v:
            return None
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.strptime(v, fmt)
                return dt.date() if fmt == "%Y-%m-%d" else dt
            except:
                pass
        return None

    sku = fstr('sku')
    title = fstr('title')

    if not sku or not title:
        return None

    ld = fdate('listing_date')

    return {
        'sku': sku,
        'title': title,
        'listing_link': fstr('listing_link'),
        'web_url': fstr('web_url'),
        'ebay_url': fstr('ebay_url'),
        'amazon_url': fstr('amazon_url'),
        'mercari_url': fstr('mercari_url'),
        'vinted_url': fstr('vinted_url'),
        'poshmark_url': fstr('poshmark_url'),
        'depop_url': fstr('depop_url'),
        'A': fstr('A'),
        'B': fstr('B'),
        'S': fstr('S'),
        'C': fstr('C'),
        'location_code': fstr('location_code'),
        'item_thumb': fstr('item_thumb'),
        'supplier': fstr('supplier'),
        'item_cost': ffloat('item_cost'),
        'item_price': ffloat('item_price'),
        'listing_date': ld if isinstance(ld, date) else None
    }


@main_bp.route("/import/csv", methods=["GET", "POST"])
@login_required
def import_csv():
    if request.method == "GET":
        return render_template("import_csv.html")

    if 'csv_file' not in request.files:
        flash("No file selected.", "error")
        return redirect(url_for('main.import_csv'))

    file = request.files['csv_file']
    if file.filename == '' or not file.filename.lower().endswith('.csv'):
        flash("Please select a valid CSV file.", "error")
        return redirect(url_for('main.import_csv'))

    mode = request.form.get('import_mode', 'add')

    try:
        csv_content = file.read().decode('utf-8')
        csv_reader = csv.DictReader(io.StringIO(csv_content))

        # Detectar formato del CSV
        csv_format = _detect_csv_format(csv_reader.fieldnames)

        if csv_format == 'unknown':
            flash("CSV format not recognized. Please use Qventory format or supported external formats (Flipwise).", "error")
            return redirect(url_for('main.import_csv'))

        imported_count = 0
        updated_count = 0
        skipped_count = 0
        duplicate_count = 0
        matched_and_updated_count = 0  # New: items updated by title match
        limit_reached_count = 0  # Track items skipped due to plan limit

        # Build a dictionary of existing items indexed by normalized title
        existing_items_by_title = {}
        for item in Item.query.filter_by(user_id=current_user.id).all():
            normalized_title = item.title.lower().strip()
            existing_items_by_title[normalized_title] = item

        # Set para detectar duplicados por título en el CSV
        seen_titles = set()

        for row in csv_reader:
            # Parsear según el formato detectado
            if csv_format == 'qventory':
                parsed_data = _parse_qventory_row(row)
            elif csv_format == 'flipwise':
                parsed_data = _parse_external_row_to_qventory(row, current_user.id)
            else:
                skipped_count += 1
                continue

            if not parsed_data:
                skipped_count += 1
                continue

            # Normalize title for matching
            title_normalized = parsed_data['title'].lower().strip()

            # Check if this title already exists in the database
            existing_item = existing_items_by_title.get(title_normalized)

            if existing_item:
                # Item exists - update ONLY supplier and cost if present in CSV
                updated_fields = []

                if parsed_data.get('supplier') is not None:
                    existing_item.supplier = parsed_data['supplier']
                    updated_fields.append('supplier')

                if parsed_data.get('item_cost') is not None:
                    existing_item.item_cost = parsed_data['item_cost']
                    updated_fields.append('cost')

                if updated_fields:
                    matched_and_updated_count += 1
                else:
                    # Title matched but no usable data to update
                    skipped_count += 1

                # Mark as seen to avoid processing duplicates in CSV
                seen_titles.add(title_normalized)
                continue

            # No existing item found by title - check if duplicate in CSV
            if title_normalized in seen_titles:
                duplicate_count += 1
                continue

            seen_titles.add(title_normalized)

            # For new items, check by SKU as well (legacy behavior)
            sku = parsed_data['sku']
            existing_item_by_sku = Item.query.filter_by(user_id=current_user.id, sku=sku).first()

            if existing_item_by_sku and mode == 'add':
                # Actualizar item existente por SKU
                for key, value in parsed_data.items():
                    if key != 'sku':  # No actualizar el SKU
                        setattr(existing_item_by_sku, key, value)
                updated_count += 1

            elif not existing_item_by_sku:
                # Check if user can add more items (plan limit)
                if not current_user.can_add_items():
                    limit_reached_count += 1
                    # Stop importing and notify user
                    break

                # Crear nuevo item
                new_item = Item(user_id=current_user.id, **parsed_data)
                db.session.add(new_item)
                imported_count += 1
                # Add to existing_items_by_title to prevent duplicates in same CSV
                existing_items_by_title[title_normalized] = new_item

        if mode == 'replace':
            # En modo replace, eliminar items que no están en el CSV
            csv_skus = {parsed_data['sku'] for parsed_data in
                       [_parse_qventory_row(r) if csv_format == 'qventory' else _parse_external_row_to_qventory(r, current_user.id)
                        for r in csv.DictReader(io.StringIO(csv_content))]
                       if parsed_data}
            items_to_delete = Item.query.filter_by(user_id=current_user.id).filter(~Item.sku.in_(csv_skus)).all()

            # Delete images from Cloudinary before deleting items
            from qventory.helpers.image_processor import delete_cloudinary_image
            for item in items_to_delete:
                if item.item_thumb:
                    delete_cloudinary_image(item.item_thumb)
                db.session.delete(item)

        db.session.commit()

        messages = []
        messages.append(f"Format detected: {csv_format.upper()}")
        if imported_count > 0:
            messages.append(f"{imported_count} items imported")
        if updated_count > 0:
            messages.append(f"{updated_count} items updated (by SKU)")
        if matched_and_updated_count > 0:
            messages.append(f"{matched_and_updated_count} items updated (by title match)")
        if duplicate_count > 0:
            messages.append(f"{duplicate_count} duplicates skipped")
        if skipped_count > 0:
            messages.append(f"{skipped_count} rows skipped")

        # Show appropriate message based on whether limit was reached
        if limit_reached_count > 0:
            remaining = current_user.items_remaining()
            plan_name = "Premium or Pro" if not current_user.is_premium else "current"
            flash(f"Import stopped: Plan limit reached. {', '.join(messages)}. Upgrade to {plan_name} plan for more items.", "error")
        else:
            flash(f"Import completed: {', '.join(messages)}.", "ok")

    except Exception as e:
        db.session.rollback()
        flash(f"Import failed: {str(e)}", "error")

    return redirect(url_for('main.dashboard'))


# ---------------------- Import from eBay (OAuth-based) ----------------------

@main_bp.route("/import/ebay", methods=["GET", "POST"])
@login_required
def import_ebay():
    """Import inventory from connected eBay seller account"""
    import sys
    import traceback

    def log_import(msg):
        print(f"[EBAY_IMPORT] {msg}", file=sys.stderr, flush=True)

    log_import("=== IMPORT ROUTE CALLED ===")

    from qventory.models.marketplace_credential import MarketplaceCredential

    # Check if user has connected eBay account
    ebay_cred = MarketplaceCredential.query.filter_by(
        user_id=current_user.id,
        marketplace='ebay',
        is_active=True
    ).first()

    ebay_connected = ebay_cred is not None
    ebay_username = ebay_cred.ebay_user_id if ebay_cred else None

    log_import(f"User: {current_user.id} ({current_user.username})")
    log_import(f"eBay connected: {ebay_connected}")
    log_import(f"eBay username: {ebay_username}")

    if request.method == "GET":
        log_import("GET request - rendering template")
        return render_template(
            "import_ebay.html",
            ebay_connected=ebay_connected,
            ebay_username=ebay_username
        )

    # POST - Start async import
    log_import("POST request - starting async import")

    if not ebay_connected:
        log_import("ERROR: eBay account not connected")
        return jsonify({"ok": False, "error": "eBay account not connected"}), 400

    # Check if user can import (check limits)
    items_remaining = current_user.items_remaining()
    log_import(f"User items remaining: {items_remaining}")

    if items_remaining is not None and items_remaining == 0:
        log_import("ERROR: User has reached item limit")
        return jsonify({
            "ok": False,
            "error": f"You have reached your plan limit. Upgrade to import more items.",
            "upgrade_required": True
        }), 403

    try:
        from qventory.tasks import import_ebay_complete as import_task
        from qventory.models.import_job import ImportJob

        # Check if there's already an import running for this user
        existing_job = ImportJob.query.filter(
            ImportJob.user_id == current_user.id,
            ImportJob.status.in_(['pending', 'processing'])
        ).first()

        if existing_job:
            log_import(f"⚠️  Import already running (Job ID: {existing_job.id})")
            return jsonify({
                "ok": False,
                "error": "An import is already in progress. Please wait for it to finish.",
                "job_id": existing_job.id
            }), 409  # 409 Conflict

        import_mode = request.form.get('import_mode', 'sync_all')
        listing_status = request.form.get('listing_status', 'ACTIVE')
        days_back = request.form.get('days_back', None)  # For sales import (None = all time)

        # Convert to int or None (empty string should be None)
        if days_back:
            try:
                days_back = int(days_back)
                if days_back <= 0:
                    days_back = None
            except (ValueError, TypeError):
                days_back = None
        else:
            days_back = None

        log_import(f"Import mode: {import_mode}")
        log_import(f"Listing status: {listing_status}")
        log_import(f"Sales days back: {days_back if days_back else 'ALL TIME'}")

        # Start COMPLETE Celery task (inventory + sales)
        log_import("Dispatching COMPLETE import task (inventory + sales)...")
        task = import_task.delay(
            current_user.id,
            import_mode=import_mode,
            listing_status=listing_status,
            days_back=days_back
        )

        log_import(f"Task dispatched: {task.id}")

        return jsonify({
            "ok": True,
            "task_id": task.id,
            "message": "Complete import started (inventory + sales). You'll be notified when finished."
        })

    except Exception as e:
        log_import(f"ERROR: {str(e)}")
        db.session.rollback()
        return jsonify({"ok": False, "error": str(e)}), 500


@main_bp.route("/sync-ebay-inventory", methods=["POST"])
@login_required
def sync_ebay_inventory():
    """
    Sync existing active inventory with eBay
    Updates prices, status, and other details for items already in database
    """
    from qventory.models.marketplace_credential import MarketplaceCredential
    from qventory.helpers.ebay_inventory import fetch_active_listings_snapshot

    # Check eBay connection
    ebay_cred = MarketplaceCredential.query.filter_by(
        user_id=current_user.id,
        marketplace='ebay',
        is_active=True
    ).first()

    if not ebay_cred:
        return jsonify({
            'success': False,
            'error': 'eBay account not connected'
        }), 400

    # God mode bypasses all plan limits
    # DEBUG: Log user role and god mode status
    print(f"[SYNC_INVENTORY] User {current_user.id} - role: {current_user.role}, is_god_mode: {current_user.is_god_mode}", file=sys.stderr)

    # Get plan limits (needed for both checks and later sync limiting)
    plan_limits = current_user.get_plan_limits()

    if not current_user.is_god_mode:
        # Verify the user can use marketplace integrations
        if plan_limits.max_marketplace_integrations == 0:
            return jsonify({
                'success': False,
                'error': 'Marketplace syncing is not available on your plan. Upgrade to sync with eBay.',
                'upgrade_required': True
            }), 403

        # Check how many items they're trying to sync vs their plan limit
        current_item_count = Item.query.filter_by(user_id=current_user.id).count()

        # Free plan should only sync up to their max_items limit
        if plan_limits.max_items is not None:
            if current_item_count >= plan_limits.max_items:
                return jsonify({
                    'success': False,
                    'error': f'You have reached your plan limit ({plan_limits.max_items} items). Upgrade to sync more items.',
                    'upgrade_required': True,
                    'current_count': current_item_count,
                    'max_allowed': plan_limits.max_items
                }), 403

    try:
        # Get all items with eBay listing IDs
        items_query = Item.query.filter(
            Item.user_id == current_user.id,
            or_(
                Item.ebay_listing_id.isnot(None),
                Item.ebay_sku.isnot(None)
            )
        )

        # Limit sync to plan limits (only for non-god users)
        if not current_user.is_god_mode and plan_limits.max_items is not None:
            # Only sync up to the plan limit
            items_to_sync = items_query.limit(plan_limits.max_items).all()
        else:
            items_to_sync = items_query.all()

        if not items_to_sync:
            return jsonify({
                'success': True,
                'message': 'No items with eBay listings to sync',
                'updated': 0
            })

        print(f"[SYNC_INVENTORY] Found {len(items_to_sync)} items to sync", file=sys.stderr)

        # Fetch current data from eBay (Offers + Trading snapshot)
        result = fetch_active_listings_snapshot(current_user.id)

        if not result['success']:
            return jsonify({
                'success': False,
                'error': result.get('error', 'Failed to fetch eBay data')
            }), 400

        offers_by_listing = {
            offer.get('ebay_listing_id'): offer
            for offer in result['offers']
            if offer.get('ebay_listing_id')
        }
        offers_by_sku = {
            offer.get('ebay_sku'): offer
            for offer in result['offers']
            if offer.get('ebay_sku')
        }
        can_mark_inactive = result.get('can_mark_inactive', False)
        sources = ', '.join(result.get('sources', [])) or 'unknown'
        print(f"[SYNC_INVENTORY] Sources: {sources} | offers: {len(result.get('offers', []))} | can_mark_inactive={can_mark_inactive}", file=sys.stderr)

        # Update each item
        updated_count = 0
        deleted_count = 0
        skipped_inactive = 0

        for item in items_to_sync:
            offer_data = None

            if item.ebay_listing_id and item.ebay_listing_id in offers_by_listing:
                offer_data = offers_by_listing[item.ebay_listing_id]
            elif item.ebay_sku and item.ebay_sku in offers_by_sku:
                offer_data = offers_by_sku[item.ebay_sku]

            if offer_data:
                # Item still exists on eBay - update it

                # Update price if changed
                if offer_data.get('item_price') and offer_data['item_price'] != item.item_price:
                    item.item_price = offer_data['item_price']
                    updated_count += 1

                # Update eBay URL if needed
                if offer_data.get('ebay_url') and not item.ebay_url:
                    item.ebay_url = offer_data['ebay_url']

                # Update offer ID if needed
                if offer_data.get('ebay_offer_id'):
                    item.ebay_offer_id = offer_data['ebay_offer_id']

                # Backfill listing ID / SKU when missing locally
                if not item.ebay_listing_id and offer_data.get('ebay_listing_id'):
                    item.ebay_listing_id = offer_data['ebay_listing_id']
                if not item.ebay_sku and offer_data.get('ebay_sku'):
                    item.ebay_sku = offer_data['ebay_sku']

                # Update listing status
                listing_status = str(offer_data.get('listing_status', 'ACTIVE')).upper()
                ended_statuses = {'ENDED', 'UNPUBLISHED', 'INACTIVE', 'CLOSED', 'ARCHIVED', 'CANCELED'}
                active_statuses = {'PUBLISHED', 'ACTIVE', 'IN_PROGRESS', 'SCHEDULED', 'ON_HOLD', 'LIVE'}

                if listing_status in ended_statuses:
                    if item.is_active:
                        item.is_active = False
                        updated_count += 1
                elif listing_status in active_statuses or not listing_status:
                    if not item.is_active:
                        item.is_active = True
            else:
                if can_mark_inactive:
                    # SOFT DELETE: Item no longer exists on eBay (sold/removed) - mark as inactive
                    print(f"[SYNC_INVENTORY] Item no longer on eBay, marking inactive: {item.title} (ID: {item.id}, eBay: {item.ebay_listing_id})", file=sys.stderr)
                    if item.is_active:
                        item.is_active = False
                        deleted_count += 1
                else:
                    skipped_inactive += 1

        db.session.commit()

        print(f"[SYNC_INVENTORY] Updated {updated_count} items, marked {deleted_count} items as inactive (skipped inactive: {skipped_inactive})", file=sys.stderr)

        return jsonify({
            'success': True,
            'message': f'Synced {len(items_to_sync)} items: {updated_count} updated, {deleted_count} marked inactive (sold/inactive on eBay)',
            'total': len(items_to_sync),
            'updated': updated_count,
            'deleted': deleted_count,
            'inactive_skipped': skipped_inactive
        })

    except Exception as e:
        db.session.rollback()
        print(f"[SYNC_INVENTORY] Error: {str(e)}", file=sys.stderr)
        return jsonify({
            'success': False,
            'error': f'Sync failed: {str(e)}'
        }), 500


@main_bp.route("/sync-ebay-sold", methods=["POST"])
@login_required
def sync_ebay_sold():
    """
    Sync sold items with eBay (ASYNC via Celery)
    Triggers a background task to fetch recent sold orders
    """
    from qventory.models.marketplace_credential import MarketplaceCredential
    from qventory.tasks import import_ebay_sales

    # Check eBay connection
    ebay_cred = MarketplaceCredential.query.filter_by(
        user_id=current_user.id,
        marketplace='ebay',
        is_active=True
    ).first()

    if not ebay_cred:
        return jsonify({
            'success': False,
            'error': 'eBay account not connected'
        }), 400

    try:
        # Determine historical range
        days_back_param = request.form.get('days_back') or request.args.get('days_back')
        try:
            sync_days_back = int(days_back_param) if days_back_param else 30  # Default 30 days
        except (TypeError, ValueError):
            sync_days_back = 30

        # Trigger async Celery task
        task = import_ebay_sales.delay(current_user.id, days_back=sync_days_back)

        print(f"[SYNC_SOLD] Started async task {task.id} for user {current_user.id}, days_back={sync_days_back}", file=sys.stderr)

        return jsonify({
            'success': True,
            'message': f'Sales sync started! Checking last {sync_days_back} days. This may take a few minutes.',
            'task_id': task.id
        })

    except Exception as e:
        print(f"[SYNC_SOLD] Error starting task: {str(e)}", file=sys.stderr)
        return jsonify({
            'success': False,
            'error': f'Failed to start sync: {str(e)}'
        }), 500


# API endpoint to check import job status
@main_bp.route("/api/import/status/<int:job_id>")
@login_required
def import_job_status(job_id):
    """Get status of import job"""
    from qventory.models.import_job import ImportJob

    job = ImportJob.query.filter_by(id=job_id, user_id=current_user.id).first()

    if not job:
        return jsonify({"ok": False, "error": "Job not found"}), 404

    return jsonify({"ok": True, "job": job.to_dict()})


# Failed imports management
@main_bp.route("/import/failed")
@login_required
def failed_imports():
    """View failed import items"""
    from qventory.models.failed_import import FailedImport

    # Get all unresolved failed imports
    failed = FailedImport.get_unresolved_for_user(current_user.id)

    return render_template("failed_imports.html", failed_imports=failed)


@main_bp.route("/api/import/retry", methods=["POST"])
@login_required
def retry_failed_imports_api():
    """API endpoint to retry failed imports"""
    from qventory.tasks import retry_failed_imports

    # Get optional list of specific IDs to retry
    data = request.get_json() or {}
    failed_import_ids = data.get('failed_import_ids')  # None = retry all

    # Start retry task
    task = retry_failed_imports.delay(current_user.id, failed_import_ids)

    return jsonify({
        "ok": True,
        "task_id": task.id,
        "message": "Retry task started. Refresh the page in a moment to see results."
    })


@main_bp.route("/api/import/rematch_sales", methods=["POST"])
@login_required
def rematch_sales_api():
    """API endpoint to rematch unlinked sales to items"""
    from qventory.tasks import rematch_sales_to_items

    # Start rematch task
    task = rematch_sales_to_items.delay(current_user.id)

    return jsonify({
        "ok": True,
        "task_id": task.id,
        "message": "Rematch task started. This will match historical sales to items in your inventory."
    })


@main_bp.route("/api/import/failed/<int:failed_id>/resolve", methods=["POST"])
@login_required
def resolve_failed_import(failed_id):
    """Mark a failed import as manually resolved"""
    from qventory.models.failed_import import FailedImport

    failed = FailedImport.query.filter_by(
        id=failed_id,
        user_id=current_user.id
    ).first()

    if not failed:
        return jsonify({"ok": False, "error": "Failed import not found"}), 404

    failed.resolved = True
    failed.resolved_at = datetime.utcnow()
    db.session.commit()

    return jsonify({"ok": True, "message": "Marked as resolved"})


# API endpoint to check for active import jobs (for global notifications)
@main_bp.route("/api/import/active")
@login_required
def active_import_job():
    """Get the most recent active import job for current user"""
    from qventory.models.import_job import ImportJob

    # Find the most recent job that's either pending or processing
    job = ImportJob.query.filter_by(user_id=current_user.id).filter(
        ImportJob.status.in_(['pending', 'processing'])
    ).order_by(ImportJob.created_at.desc()).first()

    if job:
        return jsonify({"ok": True, "has_active": True, "job": job.to_dict()})

    # Check for recently completed jobs (within last 30 seconds) that haven't been notified
    from datetime import datetime, timedelta
    recent_cutoff = datetime.utcnow() - timedelta(seconds=30)

    recent_job = ImportJob.query.filter_by(user_id=current_user.id).filter(
        ImportJob.status == 'completed',
        ImportJob.completed_at >= recent_cutoff
    ).order_by(ImportJob.completed_at.desc()).first()

    if recent_job:
        return jsonify({"ok": True, "has_active": False, "recent_completion": recent_job.to_dict()})

    return jsonify({"ok": True, "has_active": False})


# eBay import is now handled by Celery task
# See tasks.py for implementation


# ---------------------- eBay Browse API ----------------------

EBAY_ENV = (os.environ.get("EBAY_ENV") or "production").lower()
EBAY_CLIENT_ID = os.environ.get("EBAY_CLIENT_ID")
EBAY_CLIENT_SECRET = os.environ.get("EBAY_CLIENT_SECRET")

def _ebay_base():
    if EBAY_ENV == "sandbox":
        return {
            "oauth": "https://api.sandbox.ebay.com/identity/v1/oauth2/token",
            "browse": "https://api.sandbox.ebay.com/buy/browse/v1",
        }
    return {
        "oauth": "https://api.ebay.com/identity/v1/oauth2/token",
        "browse": "https://api.ebay.com/buy/browse/v1",
    }

_EBAY_TOKEN = {"value": None, "exp": 0}

def _get_ebay_app_token() -> str:
    if not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET:
        raise RuntimeError("Faltan EBAY_CLIENT_ID / EBAY_CLIENT_SECRET en .env")
    base = _ebay_base()
    now = time.time()
    if _EBAY_TOKEN["value"] and _EBAY_TOKEN["exp"] - 60 > now:
        return _EBAY_TOKEN["value"]

    basic = base64.b64encode(f"{EBAY_CLIENT_ID}:{EBAY_CLIENT_SECRET}".encode()).decode()
    data = { "grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope" }
    headers = { "Content-Type": "application/x-www-form-urlencoded", "Authorization": f"Basic {basic}" }
    r = requests.post(base["oauth"], headers=headers, data=data, timeout=15)
    r.raise_for_status()
    j = r.json()
    _EBAY_TOKEN["value"] = j["access_token"]
    _EBAY_TOKEN["exp"] = now + int(j.get("expires_in", 7200))
    return _EBAY_TOKEN["value"]


# ---------------------- Utilidades URL eBay ----------------------

_EBAY_HOSTS = (
    "ebay.com", "www.ebay.com", "m.ebay.com",
    "ebay.co.uk", "www.ebay.co.uk", "m.ebay.co.uk",
    "ebay.ca", "www.ebay.ca", "m.ebay.ca",
)

def _looks_like_ebay_store_or_search(path: str) -> bool:
    return bool(re.match(r"^/(?:str|sch|b)/", path, re.I))

def _extract_legacy_id(url: str) -> str | None:
    try:
        u = urlparse(url)
        path = u.path or ""
        if _looks_like_ebay_store_or_search(path):
            return None
        rx_list = [
            r"/itm/(?:[^/]+/)?(\d{9,})",
            r"/itm/(\d{9,})",
            r"/(\d{12})(?:[/?]|$)",
        ]
        for rx in rx_list:
            m = re.search(rx, path)
            if m:
                return m.group(1)
        qs = parse_qs(u.query)
        for key in ("item", "iid", "itemid", "legacyItemId", "itemId"):
            vals = qs.get(key)
            if vals and len(vals) > 0:
                m = re.search(r"\d{9,}", vals[0])
                if m:
                    return m.group(0)
        m = re.search(r"(\d{12,})", url)
        return m.group(1) if m else None
    except Exception:
        return None


# ---------------------- API helper eBay ----------------------

@main_bp.route("/api/fetch-market-title")
@login_required
def api_fetch_market_title():
    raw_url = (request.args.get("url") or "").strip()
    if not raw_url:
        return jsonify({"ok": False, "error": "Missing url"}), 400
    if not re.match(r"^https?://", raw_url, re.I):
        return jsonify({"ok": False, "error": "Invalid URL"}), 400

    u = urlparse(raw_url)
    host = (u.netloc or "").lower()
    path = u.path or ""

    if any(host.endswith(h) for h in _EBAY_HOSTS) and _looks_like_ebay_store_or_search(path):
        return jsonify({
            "ok": False,
            "error": "La URL de eBay parece de tienda/búsqueda/categoría. Proporciona el enlace directo del producto (/itm/...)."
        }), 400

    legacy_id = _extract_legacy_id(raw_url)
    if not legacy_id:
        return jsonify({
            "ok": False,
            "error": "No se pudo extraer el legacy_item_id. Asegúrate de usar una URL de ítem de eBay (/itm/...)."
        }), 400

    base = _ebay_base()
    try:
        token = _get_ebay_app_token()
        r = requests.get(
            f"{base['browse']}/item/get_item_by_legacy_id",
            params={"legacy_item_id": legacy_id},
            headers={"Authorization": f"Bearer {token}"},
            timeout=15
        )

        if r.status_code == 403:
            return jsonify({
                "ok": False,
                "error": f"403 Forbidden: la app no tiene acceso a Browse API en {EBAY_ENV} (o keyset deshabilitado)."
            }), 403
        if r.status_code == 404:
            return jsonify({ "ok": False, "error": "404: legacy_item_id no encontrado por Browse API en este entorno." }), 404

        r.raise_for_status()
        data = r.json()
        title = (data.get("title") or "").strip()
        item_web_url = (data.get("itemWebUrl") or raw_url).strip()
        if not title:
            return jsonify({"ok": False, "error": "La Browse API no devolvió título para este ítem."}), 502

        return jsonify({
            "ok": True,
            "marketplace": "ebay",
            "title": title,
            "fill": {"title": title, "ebay_url": item_web_url}
        })
    except requests.HTTPError as e:
        body = e.response.text[:300] if e.response is not None else ""
        code = e.response.status_code if e.response is not None else 502
        return jsonify({"ok": False, "error": f"HTTP {code}: {body}"}), code
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 502


# ---------------------- API: Upload imagen a Cloudinary ----------------------

@main_bp.route("/api/upload-image", methods=["POST"])
@login_required
def api_upload_image():
    if not cloudinary_enabled:
        return jsonify({"ok": False, "error": "Cloudinary not configured"}), 503

    f = request.files.get("file")
    if not f:
        return jsonify({"ok": False, "error": "Missing file"}), 400

    # Validación simple
    ct = (f.mimetype or "").lower()
    if not ct.startswith("image/"):
        return jsonify({"ok": False, "error": "Only image files are allowed"}), 400

    # Opcional: límite de ~8 MB
    f.seek(0, io.SEEK_END)
    size = f.tell()
    f.seek(0)
    if size > 8 * 1024 * 1024:
        return jsonify({"ok": False, "error": "Image too large (max 8MB)"}), 400

    try:
        up = cloudinary.uploader.upload(
            f,
            folder=CLOUDINARY_UPLOAD_FOLDER,
            overwrite=True,
            resource_type="image",
            transformation=[{"quality": "auto", "fetch_format": "auto"}]
        )
        url = up.get("secure_url") or up.get("url")
        public_id = up.get("public_id")
        width = up.get("width")
        height = up.get("height")
        return jsonify({"ok": True, "url": url, "public_id": public_id, "width": width, "height": height})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 502


# ---------------------- CRUD Items (protegido) ----------------------

def _parse_float(s: str | None):
    if s is None or s == "":
        return None
    try:
        return float(s)
    except:
        return None

def _parse_date(s: str | None):
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d",):
        try:
            return datetime.strptime(s, fmt).date()
        except:
            pass
    return None

@main_bp.route("/item/new", methods=["GET", "POST"])
@login_required
def new_item():
    s = get_or_create_settings(current_user)

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        listing_link = (request.form.get("listing_link") or "").strip() or None

        web_url     = (request.form.get("web_url") or "").strip() or None
        ebay_url    = (request.form.get("ebay_url") or "").strip() or None
        amazon_url  = (request.form.get("amazon_url") or "").strip() or None
        mercari_url = (request.form.get("mercari_url") or "").strip() or None
        vinted_url  = (request.form.get("vinted_url") or "").strip() or None
        poshmark_url= (request.form.get("poshmark_url") or "").strip() or None
        depop_url   = (request.form.get("depop_url") or "").strip() or None

        # Nuevos campos
        item_thumb  = (request.form.get("item_thumb") or "").strip() or None
        supplier    = (request.form.get("supplier") or "").strip() or None
        item_cost   = _parse_float(request.form.get("item_cost"))
        item_price  = _parse_float(request.form.get("item_price"))
        listing_date= _parse_date(request.form.get("listing_date"))

        A  = (request.form.get("A") or "").strip() or None
        B  = (request.form.get("B") or "").strip() or None
        S_ = (request.form.get("S") or "").strip() or None
        C  = (request.form.get("C") or "").strip() or None

        if not title:
            flash("Title is required.", "error")
            return redirect(url_for("main.new_item"))

        sku = generate_sku()
        loc = compose_location_code(A=A, B=B, S=S_, C=C, enabled=tuple(s.enabled_levels()))
        it = Item(
            user_id=current_user.id,
            title=title,
            sku=sku,
            listing_link=listing_link,
            web_url=web_url, ebay_url=ebay_url, amazon_url=amazon_url,
            mercari_url=mercari_url, vinted_url=vinted_url, poshmark_url=poshmark_url, depop_url=depop_url,
            A=A, B=B, S=S_, C=C, location_code=loc,
            # nuevos
            item_thumb=item_thumb, supplier=supplier, item_cost=item_cost, item_price=item_price, listing_date=listing_date
        )
        db.session.add(it)
        db.session.commit()

        action = (request.form.get("submit_action") or "create").strip()
        if action == "create_another":
            flash("Item created. You can add another.", "ok")
            return render_template("new_item.html", settings=s, item=None, cloudinary_enabled=cloudinary_enabled)

        flash("Item created.", "ok")
        return redirect(url_for("main.dashboard"))

    return render_template("new_item.html", settings=s, item=None, cloudinary_enabled=cloudinary_enabled)


@main_bp.route("/item/<int:item_id>/edit", methods=["GET", "POST"])
@login_required
def edit_item(item_id):
    it = Item.query.filter_by(id=item_id, user_id=current_user.id).first_or_404()
    s = get_or_create_settings(current_user)
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        listing_link = (request.form.get("listing_link") or "").strip() or None

        web_url = (request.form.get("web_url") or "").strip() or None
        ebay_url = (request.form.get("ebay_url") or "").strip() or None
        amazon_url = (request.form.get("amazon_url") or "").strip() or None
        mercari_url = (request.form.get("mercari_url") or "").strip() or None
        vinted_url = (request.form.get("vinted_url") or "").strip() or None
        poshmark_url = (request.form.get("poshmark_url") or "").strip() or None
        depop_url = (request.form.get("depop_url") or "").strip() or None

        # Nuevos campos
        item_thumb  = (request.form.get("item_thumb") or "").strip() or None
        supplier    = (request.form.get("supplier") or "").strip() or None
        item_cost   = _parse_float(request.form.get("item_cost"))
        item_price  = _parse_float(request.form.get("item_price"))
        listing_date= _parse_date(request.form.get("listing_date"))

        A = (request.form.get("A") or "").strip() or None
        B = (request.form.get("B") or "").strip() or None
        S_ = (request.form.get("S") or "").strip() or None
        C = (request.form.get("C") or "").strip() or None

        if not title:
            flash("Title is required.", "error")
            return redirect(url_for("main.edit_item", item_id=item_id))

        it.title = title
        it.listing_link = listing_link
        it.web_url = web_url
        it.ebay_url = ebay_url
        it.amazon_url = amazon_url
        it.mercari_url = mercari_url
        it.vinted_url = vinted_url
        it.poshmark_url = poshmark_url
        it.depop_url = depop_url

        it.item_thumb = item_thumb
        it.supplier = supplier
        it.item_cost = item_cost
        it.item_price = item_price
        it.listing_date = listing_date

        it.A, it.B, it.S, it.C = A, B, S_, C
        it.location_code = compose_location_code(A=A, B=B, S=S_, C=C, enabled=tuple(s.enabled_levels()))
        db.session.commit()

        # Check if user wants to sync to eBay
        sync_to_ebay = request.form.get("sync_to_ebay") == "true"

        if sync_to_ebay and it.ebay_listing_id and it.location_code:
            from qventory.helpers.ebay_inventory import sync_location_to_ebay_sku
            success = sync_location_to_ebay_sku(current_user.id, it.ebay_listing_id, it.location_code)
            if success:
                flash(f"Item updated and synced to eBay (SKU: {it.location_code})", "ok")
            else:
                flash("Item updated, but eBay sync failed. Please try again later.", "error")
        else:
            flash("Item updated.", "ok")

        # Redirect back to the page user was on (active, sold, etc.)
        return redirect(request.referrer or url_for("main.dashboard"))
    return render_template("edit_item.html", item=it, settings=s, cloudinary_enabled=cloudinary_enabled)


@main_bp.route("/item/<int:item_id>/delete", methods=["POST"])
@login_required
def delete_item(item_id):
    it = Item.query.filter_by(id=item_id, user_id=current_user.id).first_or_404()

    # Delete image from Cloudinary if it exists
    if it.item_thumb:
        from qventory.helpers.image_processor import delete_cloudinary_image
        delete_cloudinary_image(it.item_thumb)

    db.session.delete(it)
    db.session.commit()
    flash("Item deleted.", "ok")
    # Redirect back to the page user was on (active, sold, etc.)
    return redirect(request.referrer or url_for("main.dashboard"))


@main_bp.route("/sale/<int:sale_id>/update_cost", methods=["POST"])
@login_required
def update_sale_cost(sale_id):
    """
    Update item_cost for a sale and recalculate profit
    This is used from the sold items view where users need to add cost to sold items
    """
    from qventory.models.sale import Sale

    sale = Sale.query.filter_by(id=sale_id, user_id=current_user.id).first_or_404()

    # Get item_cost from request (supports both JSON and form data)
    if request.is_json:
        item_cost = request.json.get('item_cost')
    else:
        item_cost = request.form.get('item_cost')

    # Parse and validate item_cost
    try:
        if item_cost is not None and item_cost != '':
            item_cost = float(item_cost)
            if item_cost < 0:
                if request.is_json:
                    return jsonify({"ok": False, "error": "Item cost cannot be negative"}), 400
                flash("Item cost cannot be negative.", "error")
                return redirect(request.referrer or url_for("main.inventory_sold"))
        else:
            item_cost = None
    except (ValueError, TypeError):
        if request.is_json:
            return jsonify({"ok": False, "error": "Invalid item cost format"}), 400
        flash("Invalid item cost format.", "error")
        return redirect(request.referrer or url_for("main.inventory_sold"))

    # Update sale's item_cost
    sale.item_cost = item_cost

    # If there's a linked item, update its cost too
    if sale.item_id:
        item = Item.query.filter_by(id=sale.item_id, user_id=current_user.id).first()
        if item and item_cost is not None:
            item.item_cost = item_cost

    # Recalculate profit with new cost
    sale.calculate_profit()

    db.session.commit()

    if request.is_json:
        return jsonify({
            "ok": True,
            "sale_id": sale.id,
            "item_cost": sale.item_cost,
            "gross_profit": sale.gross_profit,
            "net_profit": sale.net_profit
        })

    flash("Item cost updated and profit recalculated.", "ok")
    return redirect(request.referrer or url_for("main.inventory_sold"))


@main_bp.route("/items/bulk_delete", methods=["POST"])
@login_required
def bulk_delete_items():
    """
    Bulk delete multiple items
    Expects JSON: {"item_ids": [1, 2, 3, ...]}
    """
    try:
        data = request.get_json()
        if not data or 'item_ids' not in data:
            return jsonify({"ok": False, "error": "Missing item_ids"}), 400

        item_ids = data['item_ids']

        # Validate item_ids is a list
        if not isinstance(item_ids, list):
            return jsonify({"ok": False, "error": "item_ids must be an array"}), 400

        # Convert to integers
        try:
            item_ids = [int(x) for x in item_ids]
        except (ValueError, TypeError):
            return jsonify({"ok": False, "error": "Invalid item ID format"}), 400

        if len(item_ids) == 0:
            return jsonify({"ok": False, "error": "No items selected"}), 400

        # Get items to delete (to access image URLs before deletion)
        items_to_delete = Item.query.filter(
            Item.id.in_(item_ids),
            Item.user_id == current_user.id
        ).all()

        # Delete images from Cloudinary
        from qventory.helpers.image_processor import delete_cloudinary_image
        deleted_images = 0
        for item in items_to_delete:
            if item.item_thumb:
                if delete_cloudinary_image(item.item_thumb):
                    deleted_images += 1

        # Delete items from database
        deleted_count = len(items_to_delete)
        for item in items_to_delete:
            db.session.delete(item)

        db.session.commit()

        return jsonify({
            "ok": True,
            "deleted_count": deleted_count,
            "deleted_images": deleted_images,
            "message": f"Successfully deleted {deleted_count} item(s) and {deleted_images} image(s)"
        })

    except Exception as e:
        db.session.rollback()
        print(f"[BULK_DELETE] Error: {str(e)}", file=sys.stderr)
        return jsonify({"ok": False, "error": str(e)}), 500


@main_bp.route("/item/sync_to_ebay", methods=["POST"])
@login_required
def sync_item_to_ebay():
    """
    Sync single item location to eBay Custom SKU
    Expects JSON: {"item_id": 123}
    """
    try:
        data = request.get_json()
        if not data or 'item_id' not in data:
            return jsonify({"ok": False, "error": "Missing item_id"}), 400

        item_id = int(data['item_id'])
        item = Item.query.filter_by(id=item_id, user_id=current_user.id).first()

        if not item:
            return jsonify({"ok": False, "error": "Item not found"}), 404

        if not item.ebay_listing_id:
            return jsonify({"ok": False, "error": "Item not linked to eBay"}), 400

        if not item.location_code:
            return jsonify({"ok": False, "error": "Item has no location code"}), 400

        # Sync to eBay
        from qventory.helpers.ebay_inventory import sync_location_to_ebay_sku
        success = sync_location_to_ebay_sku(current_user.id, item.ebay_listing_id, item.location_code)

        if success:
            return jsonify({"ok": True, "message": "Synced to eBay"})
        else:
            return jsonify({"ok": False, "error": "Failed to sync to eBay"}), 500

    except Exception as e:
        print(f"[SYNC_TO_EBAY] Error: {str(e)}", file=sys.stderr)
        return jsonify({"ok": False, "error": str(e)}), 500


@main_bp.route("/items/bulk_assign_location", methods=["POST"])
@login_required
def bulk_assign_location():
    """
    Bulk assign location to multiple items
    Expects JSON: {
        "item_ids": [1, 2, 3, ...],
        "A": "value or null",
        "B": "value or null",
        "S": "value or null",
        "C": "value or null",
        "sync_to_ebay": true/false
    }
    """
    try:
        data = request.get_json()
        if not data or 'item_ids' not in data:
            return jsonify({"ok": False, "error": "Missing item_ids"}), 400

        item_ids = [int(x) for x in data['item_ids']]
        if len(item_ids) == 0:
            return jsonify({"ok": False, "error": "No items selected"}), 400

        # Get items
        items = Item.query.filter(
            Item.id.in_(item_ids),
            Item.user_id == current_user.id
        ).all()

        if len(items) == 0:
            return jsonify({"ok": False, "error": "No items found"}), 404

        # Get location values
        A = data.get('A')
        B = data.get('B')
        S = data.get('S')
        C = data.get('C')
        sync_to_ebay = data.get('sync_to_ebay', False)

        # Compose location code
        from qventory.helpers import compose_location_code
        location_code = compose_location_code(A, B, S, C)

        # Update items
        updated_count = 0
        synced_count = 0

        for item in items:
            item.location_A = A
            item.location_B = B
            item.location_S = S
            item.location_C = C
            item.location_code = location_code
            updated_count += 1

            # Sync to eBay if requested and item has eBay listing
            if sync_to_ebay and item.ebay_listing_id and location_code:
                from qventory.helpers.ebay_inventory import sync_location_to_ebay_sku
                success = sync_location_to_ebay_sku(current_user.id, item.ebay_listing_id, location_code)
                if success:
                    synced_count += 1

        db.session.commit()

        message = f"Successfully updated location for {updated_count} item(s)"
        if sync_to_ebay and synced_count > 0:
            message += f" and synced {synced_count} to eBay"

        return jsonify({
            "ok": True,
            "updated_count": updated_count,
            "synced_count": synced_count,
            "message": message
        })

    except Exception as e:
        print(f"[BULK_ASSIGN_LOCATION] Error: {str(e)}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        db.session.rollback()
        return jsonify({"ok": False, "error": str(e)}), 500


@main_bp.route("/items/bulk_sync_to_ebay", methods=["POST"])
@login_required
def bulk_sync_to_ebay():
    """
    Bulk sync items location to eBay Custom SKU
    Expects JSON: {"item_ids": [1, 2, 3, ...]}
    """
    try:
        data = request.get_json()
        if not data or 'item_ids' not in data:
            return jsonify({"ok": False, "error": "Missing item_ids"}), 400

        item_ids = [int(x) for x in data['item_ids']]
        if len(item_ids) == 0:
            return jsonify({"ok": False, "error": "No items selected"}), 400

        # Get items
        items = Item.query.filter(
            Item.id.in_(item_ids),
            Item.user_id == current_user.id
        ).all()

        from qventory.helpers.ebay_inventory import sync_location_to_ebay_sku

        synced_count = 0
        for item in items:
            if item.ebay_listing_id and item.location_code:
                success = sync_location_to_ebay_sku(current_user.id, item.ebay_listing_id, item.location_code)
                if success:
                    synced_count += 1

        return jsonify({
            "ok": True,
            "synced_count": synced_count,
            "message": f"Successfully synced {synced_count} item(s)"
        })

    except Exception as e:
        print(f"[BULK_SYNC] Error: {str(e)}", file=sys.stderr)
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------- Settings (protegido) ----------------------

@main_bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    s = get_or_create_settings(current_user)
    if request.method == "POST":
        s.enable_A = request.form.get("enable_A") == "on"
        s.enable_B = request.form.get("enable_B") == "on"
        s.enable_S = request.form.get("enable_S") == "on"
        s.enable_C = request.form.get("enable_C") == "on"

        s.label_A = (request.form.get("label_A") or "").strip() or "Aisle"
        s.label_B = (request.form.get("label_B") or "").strip() or "Bay"
        s.label_S = (request.form.get("label_S") or "").strip() or "Shelve"
        s.label_C = (request.form.get("label_C") or "").strip() or "Container"

        db.session.commit()
        flash("Settings saved.", "ok")
        return redirect(url_for("main.settings"))

    # Check eBay connection status
    from qventory.models.marketplace_credential import MarketplaceCredential
    ebay_cred = MarketplaceCredential.query.filter_by(
        user_id=current_user.id,
        marketplace='ebay',
        is_active=True
    ).first()

    ebay_connected = ebay_cred is not None
    ebay_username = ebay_cred.ebay_user_id if ebay_cred else None

    return render_template("settings.html",
                         settings=s,
                         ebay_connected=ebay_connected,
                         ebay_username=ebay_username)


# ---------------------- Batch QR (protegido) ----------------------

@main_bp.route("/qr/batch", methods=["GET", "POST"])
@login_required
def qr_batch():
    s = get_or_create_settings(current_user)
    if request.method == "GET":
        return render_template("batch_qr.html", settings=s)

    valsA = parse_values(request.form.get("A") or "") if s.enable_A else [""]
    valsB = parse_values(request.form.get("B") or "") if s.enable_B else [""]
    valsS = parse_values(request.form.get("S") or "") if s.enable_S else [""]
    valsC = parse_values(request.form.get("C") or "") if s.enable_C else [""]

    if s.enable_A and not valsA: valsA = [""]
    if s.enable_B and not valsB: valsB = [""]
    if s.enable_S and not valsS: valsS = [""]
    if s.enable_C and not valsC: valsC = [""]

    combos = []
    for a in valsA:
        for b in valsB:
            for s_ in valsS:
                for c in valsC:
                    code = compose_location_code(
                        A=a or None, B=b or None, S=s_ or None, C=c or None,
                        enabled=tuple(s.enabled_levels())
                    )
                    if code:
                        combos.append(code)

    if not combos:
        flash("No codes generated. Please provide at least one value.", "error")
        return redirect(url_for("main.qr_batch"))

    from ..helpers.utils import build_qr_batch_pdf
    pdf_buf = build_qr_batch_pdf(
        combos, s,
        lambda code: url_for("main.public_view_location",
                             username=current_user.username, code=code, _external=True)
    )
    return send_file(pdf_buf, mimetype="application/pdf", as_attachment=True, download_name="qr_labels.pdf")


# ---------------------- Rutas públicas por username ----------------------

@main_bp.route("/<username>/location/<code>")
def public_view_location(username, code):
    user = User.query.filter_by(username=username).first_or_404()
    s = get_or_create_settings(user)
    parts = parse_location_code(code)

    q = Item.query.filter_by(user_id=user.id)
    if s.enable_A and "A" in parts:
        q = q.filter(Item.A == parts["A"])
    if s.enable_B and "B" in parts:
        q = q.filter(Item.B == parts["B"])
    if s.enable_S and "S" in parts:
        q = q.filter(Item.S == parts["S"])
    if s.enable_C and "C" in parts:
        q = q.filter(Item.C == parts["C"])

    items = q.order_by(Item.created_at.desc()).all()
    return render_template("location.html", code=code, items=items, settings=s, parts=parts, username=username)


@main_bp.route("/<username>/qr/location/<code>.png")
def qr_for_location(username, code):
    user = User.query.filter_by(username=username).first_or_404()
    s = get_or_create_settings(user)
    parts = parse_location_code(code)
    labels = s.labels_map()
    segments = []
    if s.enable_A and parts.get("A"):
        segments.append(f"{labels['A']} {parts['A']}")
    if s.enable_B and parts.get("B"):
        segments.append(f"{labels['B']} {parts['B']}")
    if s.enable_S and parts.get("S"):
        segments.append(f"{labels['S']} {parts['S']}")
    if s.enable_C and parts.get("C"):
        segments.append(f"{labels['C']} {parts['C']}")
    human = " • ".join(segments) if segments else "Location"

    link = url_for("main.public_view_location", username=username, code=code, _external=True)
    img = qr_label_image(code, human, link, qr_px=300)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")

# ---------------------- eBay Deletion Auth ----------------------

@main_bp.get("/ebay/deletions")
def ebay_deletions_challenge():
    """
    Verificación de endpoint (GET con ?challenge_code=...).
    Responder con JSON: {"challengeResponse": "<sha256hex>"}.
    Hash = SHA256( challengeCode + verificationToken + endpointURL ).
    """
    challenge_code = request.args.get("challenge_code", "").strip()
    if not challenge_code:
        return jsonify({"error": "Missing challenge_code"}), 400

    # Validaciones mínimas
    if not EBAY_VERIFICATION_TOKEN or not EBAY_DELETIONS_ENDPOINT_URL:
        return jsonify({"error": "Server misconfigured: missing VERIFICATION_TOKEN or ENDPOINT_URL"}), 500

    # Concatenación EXACTA (orden importa)
    to_hash = f"{challenge_code}{EBAY_VERIFICATION_TOKEN}{EBAY_DELETIONS_ENDPOINT_URL}".encode("utf-8")
    response_hash = hashlib.sha256(to_hash).hexdigest()

    return jsonify({"challengeResponse": response_hash}), 200


@main_bp.post("/ebay/deletions")
def ebay_deletions_notify():
    """
    Notificaciones reales (POST). eBay puede enviarte MARKETPLACE_ACCOUNT_DELETION.
    Responde rápido 2xx como ACK; procesa en background si necesitas.
    """
    try:
        payload = request.get_json(force=True, silent=True) or {}
    except Exception:
        payload = {}

    # TODO: aquí guardas logs, encolas un job, borras datos del usuario, etc.
    # Por ahora solo ACK:
    return "", 204


# ---------------------- SEO / PWA extra ----------------------

@main_bp.route("/robots.txt")
def robots_txt():
    return Response("User-agent: *\nAllow: /\nSitemap: /sitemap.xml\n", mimetype="text/plain")


@main_bp.route("/sitemap.xml")
def sitemap_xml():
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="https://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>{request.url_root.rstrip('/')}/</loc></url>
  <url><loc>{request.url_root.rstrip('/')}/login</loc></url>
  <url><loc>{request.url_root.rstrip('/')}/register</loc></url>
</urlset>"""
    return Response(xml, mimetype="application/xml")


@main_bp.route("/sw.js")
def service_worker():
    resp = make_response(send_from_directory("static", "sw.js"))
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["Content-Type"] = "application/javascript"
    return resp


@main_bp.route("/offline")
def offline():
    return render_template("offline.html")


# ====================== helpers + ruta de IMPRESIÓN con QR ======================

def _ellipsize(s: str, n: int = 20) -> str:
    s = (s or "").strip()
    if len(s) <= n:
        return s
    return s[:n].rstrip() + "…"

def _build_item_label_pdf(it, settings) -> bytes:
    W = 40 * mm
    H = 30 * mm

    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(W, H))

    m = 3 * mm
    inner_w = W - 2 * m
    inner_h = H - 2 * m

    title_fs = 8
    loc_fs = 8
    leading = 1.2
    title_h = title_fs * leading
    loc_h = loc_fs * leading

    gap_qr_title = 1.5 * mm
    gap_title_loc = 0.8 * mm

    qr_size = 15 * mm

    block_h = qr_size + gap_qr_title + title_h + gap_title_loc + loc_h
    y0 = m + (inner_h - block_h) / 2.0

    sku = it.sku or ""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=1,
    )
    qr.add_data(sku)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white")
    if getattr(qr_img, "mode", None) != 'RGB':
        qr_img = qr_img.convert('RGB')
    x_qr = m + (inner_w - qr_size) / 2.0
    c.drawImage(ImageReader(qr_img), x_qr, y0, width=qr_size, height=qr_size, preserveAspectRatio=True)

    title = _ellipsize(it.title or "", 20)
    c.setFont("Helvetica-Bold", title_fs)
    y_title = y0 + qr_size + gap_qr_title + title_fs
    c.drawCentredString(W / 2.0, y_title, title)

    loc = it.location_code or "-"
    c.setFont("Helvetica", loc_fs)
    y_loc = y0 + qr_size + gap_qr_title + title_h + gap_title_loc + loc_fs
    c.drawCentredString(W / 2.0, y_loc, loc)

    c.showPage()
    c.save()
    pdf_bytes = buf.getvalue()
    buf.close()
    return pdf_bytes


@main_bp.route("/item/<int:item_id>/print", methods=["POST"])
@login_required
def print_item(item_id):
    it = Item.query.filter_by(id=item_id, user_id=current_user.id).first_or_404()
    s = get_or_create_settings(current_user)

    pdf_bytes = _build_item_label_pdf(it, s)

    printer_name = os.environ.get("QVENTORY_PRINTER")
    try:
        with tempfile.NamedTemporaryFile(prefix="qventory_label_", suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_bytes)
            tmp_path = tmp.name

        lp_cmd = ["lp"]
        if printer_name:
            lp_cmd += ["-d", printer_name]
        lp_cmd.append(tmp_path)

        res = subprocess.run(lp_cmd, capture_output=True, text=True, timeout=15)
        if res.returncode == 0:
            flash("Label sent to printer.", "ok")
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
            # Redirect back to the page user was on (active, sold, etc.)
            return redirect(request.referrer or url_for("main.dashboard"))
        else:
            flash("Printing failed. Downloading the label instead.", "error")
            return send_file(
                io.BytesIO(pdf_bytes),
                mimetype="application/pdf",
                as_attachment=True,
                download_name=f"label_{it.sku}.pdf",
            )
    except FileNotFoundError:
        flash("System print not available. Downloading the label.", "error")
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"label_{it.sku}.pdf",
        )
    except Exception as e:
        flash(f"Unexpected error: {e}. Downloading the label.", "error")
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"label_{it.sku}.pdf",
        )


# ==================== ADMIN BACKOFFICE ====================

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

def check_admin_auth():
    """Check if admin is authenticated via session"""
    return request.cookies.get("admin_auth") == "authenticated"

def require_admin(f):
    """Decorator to require admin authentication"""
    from functools import wraps

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not check_admin_auth():
            flash("Admin authentication required", "error")
            return redirect(url_for('main.admin_login'))
        return f(*args, **kwargs)
    return decorated_function


@main_bp.route("/admin")
def admin_redirect():
    """Redirect /admin to /admin/login"""
    return redirect(url_for('main.admin_login'))


@main_bp.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    """Admin login page"""
    if request.method == "POST":
        password = request.form.get("password", "")
        if password == ADMIN_PASSWORD:
            resp = make_response(redirect(url_for('main.admin_dashboard')))
            resp.set_cookie('admin_auth', 'authenticated', max_age=3600*24)  # 24 hours
            flash("Admin authentication successful", "ok")
            return resp
        else:
            flash("Invalid admin password", "error")

    return render_template("admin_login.html")


@main_bp.route("/admin/logout")
def admin_logout():
    """Admin logout"""
    resp = make_response(redirect(url_for('main.admin_login')))
    resp.set_cookie('admin_auth', '', expires=0)
    flash("Logged out from admin", "ok")
    return resp


@main_bp.route("/admin/dashboard")
@require_admin
def admin_dashboard():
    """Admin dashboard - view all users and their inventory stats"""
    # Get all users with item count
    users = User.query.all()
    user_stats = []

    for user in users:
        item_count = Item.query.filter_by(user_id=user.id).count()
        user_stats.append({
            'user': user,
            'item_count': item_count,
            'has_inventory': item_count > 0
        })

    # Sort by item count descending
    user_stats.sort(key=lambda x: x['item_count'], reverse=True)

    return render_template("admin_dashboard.html", user_stats=user_stats)


@main_bp.route("/admin/user/<int:user_id>/diagnostics")
@require_admin
def admin_user_diagnostics(user_id):
    """View import diagnostics for a specific user"""
    from qventory.models.failed_import import FailedImport
    from qventory.models.import_job import ImportJob
    from qventory.models.marketplace_credential import MarketplaceCredential

    user = User.query.get_or_404(user_id)

    # Get eBay connection status
    ebay_cred = MarketplaceCredential.query.filter_by(
        user_id=user_id,
        marketplace='ebay',
        is_active=True
    ).first()

    # Get inventory stats
    total_items = Item.query.filter_by(user_id=user_id).count()
    active_items = Item.query.filter_by(user_id=user_id, is_active=True).count()
    inactive_items = Item.query.filter_by(user_id=user_id, is_active=False).count()

    # Get recent import jobs
    recent_jobs = ImportJob.query.filter_by(user_id=user_id).order_by(
        ImportJob.created_at.desc()
    ).limit(10).all()

    # Get failed imports (unresolved)
    failed_imports = FailedImport.get_unresolved_for_user(user_id)

    # Group failed imports by error type
    error_summary = {}
    for failed in failed_imports:
        error_type = failed.error_type or 'unknown'
        if error_type not in error_summary:
            error_summary[error_type] = {
                'count': 0,
                'examples': []
            }
        error_summary[error_type]['count'] += 1
        if len(error_summary[error_type]['examples']) < 3:
            error_summary[error_type]['examples'].append(failed)

    return render_template(
        "admin_user_diagnostics.html",
        user=user,
        ebay_connected=ebay_cred is not None,
        total_items=total_items,
        active_items=active_items,
        inactive_items=inactive_items,
        recent_jobs=recent_jobs,
        failed_imports=failed_imports,
        error_summary=error_summary
    )


@main_bp.route("/admin/user/<int:user_id>/delete", methods=["POST"])
@require_admin
def admin_delete_user(user_id):
    """Delete a user and all their data"""
    from qventory.models.sale import Sale
    from qventory.models.import_job import ImportJob
    from qventory.models.failed_import import FailedImport
    from qventory.models.listing import Listing
    from qventory.models.report import Report
    from qventory.models.marketplace_credential import MarketplaceCredential
    from qventory.models.ai_token import AITokenUsage
    from qventory.models.subscription import Subscription
    from qventory.models.expense import Expense

    user = User.query.get_or_404(user_id)
    username = user.username

    try:
        # Delete in order to respect foreign key constraints
        # 1. Delete failed imports (references import_jobs)
        FailedImport.query.filter_by(user_id=user_id).delete()

        # 2. Delete import jobs
        ImportJob.query.filter_by(user_id=user_id).delete()

        # 3. Delete reports (references items, so must be deleted before items)
        Report.query.filter_by(user_id=user_id).delete()

        # 4. Delete listings (references items)
        Listing.query.filter_by(user_id=user_id).delete()

        # 5. Delete sales (references items via item_id)
        Sale.query.filter_by(user_id=user_id).delete()

        # 6. Delete expenses
        Expense.query.filter_by(user_id=user_id).delete()

        # 7. Delete all items belonging to this user
        Item.query.filter_by(user_id=user_id).delete()

        # 8. Delete AI token usage
        AITokenUsage.query.filter_by(user_id=user_id).delete()

        # 9. Delete marketplace credentials
        MarketplaceCredential.query.filter_by(user_id=user_id).delete()

        # 10. Delete subscription
        Subscription.query.filter_by(user_id=user_id).delete()

        # 11. Delete user settings
        Setting.query.filter_by(user_id=user_id).delete()

        # 12. Delete the user
        db.session.delete(user)
        db.session.commit()

        flash(f"User '{username}' and all their data deleted successfully", "ok")
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting user '{username}': {str(e)}", "error")

    return redirect(url_for('main.admin_dashboard'))


@main_bp.route("/admin/user/create", methods=["GET", "POST"])
@require_admin
def admin_create_user():
    """Create a new user from admin panel"""
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not username or not email or not password:
            flash("All fields are required", "error")
            return render_template("admin_create_user.html")

        # Check if user already exists
        if User.query.filter_by(username=username).first():
            flash("Username already exists", "error")
            return render_template("admin_create_user.html")

        if User.query.filter_by(email=email).first():
            flash("Email already exists", "error")
            return render_template("admin_create_user.html")

        # Create new user
        from werkzeug.security import generate_password_hash
        new_user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password)
        )
        db.session.add(new_user)
        db.session.commit()

        flash(f"User '{username}' created successfully", "ok")
        return redirect(url_for('main.admin_dashboard'))

    return render_template("admin_create_user.html")


@main_bp.route("/admin/users/roles")
@require_admin
def admin_users_roles():
    """Manage user roles for AI Research token limits"""
    # Get all users with their token stats
    from qventory.models.ai_token import AITokenUsage, AITokenConfig

    users = User.query.order_by(User.created_at.desc()).all()
    user_data = []

    for user in users:
        today_usage = AITokenUsage.get_today_usage(user.id)
        token_limit = AITokenConfig.get_token_limit(user.role)

        user_data.append({
            'user': user,
            'tokens_used_today': today_usage.tokens_used if today_usage else 0,
            'token_limit': token_limit,
            'tokens_remaining': token_limit - (today_usage.tokens_used if today_usage else 0)
        })

    return render_template("admin_user_roles.html", user_data=user_data)


@main_bp.route("/admin/user/<int:user_id>/role", methods=["POST"])
@require_admin
def admin_change_user_role(user_id):
    """Change a user's role"""
    user = User.query.get_or_404(user_id)
    new_role = request.form.get("role", "").strip().lower()

    valid_roles = ['free', 'early_adopter', 'premium', 'pro', 'god']
    if new_role not in valid_roles:
        flash(f"Invalid role. Must be one of: {', '.join(valid_roles)}", "error")
        return redirect(url_for('main.admin_users_roles'))

    old_role = user.role

    # Detect if this is an upgrade (more items allowed)
    from qventory.models.subscription import PlanLimit
    old_limits = PlanLimit.query.filter_by(plan=old_role).first()
    new_limits = PlanLimit.query.filter_by(plan=new_role).first()

    is_upgrade = False
    if old_limits and new_limits:
        old_max = old_limits.max_items if old_limits.max_items is not None else float('inf')
        new_max = new_limits.max_items if new_limits.max_items is not None else float('inf')
        is_upgrade = new_max > old_max

    # Update role
    user.role = new_role

    # Also update subscription plan to keep them in sync
    from qventory.models.subscription import Subscription
    subscription = Subscription.query.filter_by(user_id=user_id).first()
    if subscription:
        subscription.plan = new_role
        subscription.updated_at = datetime.utcnow()

    db.session.commit()

    # If upgraded and user has eBay connected, auto-resume import
    if is_upgrade:
        from qventory.models.marketplace_credential import MarketplaceCredential
        ebay_cred = MarketplaceCredential.query.filter_by(
            user_id=user_id,
            marketplace='ebay',
            is_active=True
        ).first()

        if ebay_cred:
            # Launch background import to fetch remaining eBay listings
            from qventory.tasks import import_ebay_inventory
            task = import_ebay_inventory.delay(user_id, import_mode='new_only', listing_status='ACTIVE')
            flash(f"User '{user.username}' upgraded from '{old_role}' to '{new_role}'. Auto-importing remaining eBay listings...", "ok")
        else:
            flash(f"User '{user.username}' role changed from '{old_role}' to '{new_role}'", "ok")
    else:
        flash(f"User '{user.username}' role changed from '{old_role}' to '{new_role}'", "ok")

    return redirect(url_for('main.admin_users_roles'))


@main_bp.route("/admin/resume-ebay-imports", methods=["POST"])
@require_admin
def admin_resume_ebay_imports():
    """
    ONE-TIME: Resume eBay imports for all upgraded users who have incomplete imports

    This should be run once after deploying the auto-resume feature to catch
    users who were upgraded before this functionality existed.
    """
    from qventory.tasks import resume_ebay_imports_after_upgrade

    # Launch the one-time task
    task = resume_ebay_imports_after_upgrade.delay()

    flash(f"Resume task launched (Task ID: {task.id}). Check logs for results. This will import remaining eBay listings for all upgraded users with space available.", "ok")
    return redirect(url_for('main.admin_dashboard'))


@main_bp.route("/admin/process-recurring-expenses", methods=["POST"])
@require_admin
def admin_process_recurring_expenses():
    """
    Manually trigger recurring expenses processing
    Useful for testing or if the daily cron failed
    """
    from qventory.tasks import process_recurring_expenses

    # Launch the task
    task = process_recurring_expenses.delay()

    flash(f"Recurring expenses task launched (Task ID: {task.id}). This will create expense entries for all active recurring expenses due today.", "ok")
    return redirect(url_for('main.admin_dashboard'))


@main_bp.route("/admin/sync-and-purge-items", methods=["POST"])
@require_admin
def admin_sync_and_purge_items():
    """
    Sync all eBay accounts and purge items that are no longer active

    This will:
    1. Find all users with eBay connected
    2. Sync their eBay inventory
    3. Mark items as inactive if they no longer exist on eBay
    """
    from qventory.tasks import sync_and_purge_inactive_items

    # Launch the task
    task = sync_and_purge_inactive_items.delay()

    flash(f"Sync and purge task launched (Task ID: {task.id}). This will sync all eBay accounts and mark inactive items. Check logs for results.", "ok")
    return redirect(url_for('main.admin_dashboard'))


@main_bp.route("/admin/reactivate-ebay-items", methods=["POST"])
@require_admin
def admin_reactivate_ebay_items():
    """Reactivate items marked inactive that are still active on eBay."""
    from qventory.tasks import reactivate_inactive_ebay_items

    task = reactivate_inactive_ebay_items.delay()
    flash(f"Reactivation task launched (Task ID: {task.id}). This will scan all eBay accounts and reactivate items still active on eBay.", "ok")
    return redirect(url_for('main.admin_dashboard'))


@main_bp.route("/admin/resync-all-inventory", methods=["POST"])
@require_admin
def admin_resync_all_inventory():
    """
    Global action: deduplicate every eBay inventory and launch a sync_all import.
    """
    from qventory.tasks import resync_all_inventories_and_purge

    task = resync_all_inventories_and_purge.delay()
    flash(
        f"Full resync task launched (Task ID: {task.id}). All eBay inventories will be deduplicated and synced.",
        "ok"
    )
    return redirect(url_for('main.admin_dashboard'))


@main_bp.route("/admin/tokens/config")
@require_admin
def admin_token_config():
    """Manage AI token configurations per role"""
    from qventory.models.ai_token import AITokenConfig

    configs = AITokenConfig.query.order_by(AITokenConfig.daily_tokens.desc()).all()

    return render_template("admin_token_config.html", configs=configs)


@main_bp.route("/admin/tokens/config/<string:role>", methods=["POST"])
@require_admin
def admin_update_token_config(role):
    """Update token limit for a role"""
    from qventory.models.ai_token import AITokenConfig

    new_limit = request.form.get("daily_tokens", "").strip()

    try:
        new_limit = int(new_limit)
        if new_limit < 0:
            raise ValueError("Limit must be positive")
    except ValueError:
        flash("Invalid token limit. Must be a positive number.", "error")
        return redirect(url_for('main.admin_token_config'))

    config = AITokenConfig.query.filter_by(role=role).first()
    if not config:
        flash(f"Role '{role}' not found", "error")
        return redirect(url_for('main.admin_token_config'))

    old_limit = config.daily_tokens
    config.daily_tokens = new_limit
    db.session.commit()

    flash(f"Token limit for '{role}' updated from {old_limit} to {new_limit} tokens/day", "ok")
    return redirect(url_for('main.admin_token_config'))


# ==================== PLAN LIMITS MANAGEMENT ====================

@main_bp.route("/admin/plan-limits")
@require_admin
def admin_plan_limits():
    """Manage plan limits (items, features, etc.)"""
    from qventory.models.subscription import PlanLimit

    plans = PlanLimit.query.order_by(PlanLimit.max_items.nullslast(), PlanLimit.max_items).all()

    return render_template("admin_plan_limits.html", plans=plans)


@main_bp.route("/admin/plan-limits/<string:plan>", methods=["POST"])
@require_admin
def admin_update_plan_limits(plan):
    """Update limits for a specific plan"""
    from qventory.models.subscription import PlanLimit

    plan_limit = PlanLimit.query.filter_by(plan=plan).first_or_404()

    try:
        # Parse max_items (can be empty for unlimited)
        max_items_str = request.form.get("max_items", "").strip()
        if max_items_str == "" or max_items_str.lower() == "unlimited":
            plan_limit.max_items = None
        else:
            plan_limit.max_items = int(max_items_str)
            if plan_limit.max_items < 0:
                raise ValueError("Max items must be positive")

        # Other numeric limits
        plan_limit.max_images_per_item = int(request.form.get("max_images_per_item", 1))
        plan_limit.max_marketplace_integrations = int(request.form.get("max_marketplace_integrations", 0))

        # Receipt OCR limits
        receipt_monthly_str = request.form.get("max_receipt_ocr_per_month", "").strip()
        if receipt_monthly_str == "" or receipt_monthly_str.lower() == "unlimited":
            plan_limit.max_receipt_ocr_per_month = None
        else:
            plan_limit.max_receipt_ocr_per_month = int(receipt_monthly_str)

        receipt_daily_str = request.form.get("max_receipt_ocr_per_day", "").strip()
        if receipt_daily_str == "" or receipt_daily_str.lower() == "unlimited":
            plan_limit.max_receipt_ocr_per_day = None
        else:
            plan_limit.max_receipt_ocr_per_day = int(receipt_daily_str)

        # Boolean features
        plan_limit.can_use_ai_research = request.form.get("can_use_ai_research") == "on"
        plan_limit.can_bulk_operations = request.form.get("can_bulk_operations") == "on"
        plan_limit.can_export_csv = request.form.get("can_export_csv") == "on"
        plan_limit.can_import_csv = request.form.get("can_import_csv") == "on"
        plan_limit.can_use_analytics = request.form.get("can_use_analytics") == "on"
        plan_limit.can_create_listings = request.form.get("can_create_listings") == "on"

        # Support level
        plan_limit.support_level = request.form.get("support_level", "community")

        db.session.commit()

        flash(f"Plan limits for '{plan}' updated successfully", "ok")

    except ValueError as e:
        flash(f"Error updating plan: {str(e)}", "error")

    return redirect(url_for('main.admin_plan_limits'))


# ==================== PRIVACY POLICY ====================

@main_bp.route("/privacy")
def privacy_policy():
    """Privacy policy page - compliant with eBay, Poshmark, Mercari, Depop APIs"""
    return render_template("privacy.html")


# ==================== PROFIT CALCULATOR ====================

@main_bp.route("/profit-calculator")
@login_required
def profit_calculator():
    """Standalone profit calculator page"""
    return render_template("profit_calculator.html")


@main_bp.route("/api/autocomplete-items")
@login_required
def api_autocomplete_items():
    """Autocomplete items by title, SKU, or supplier"""
    q = (request.args.get("q") or "").strip()
    view_type = request.args.get("view_type", "active")  # active, sold, ended

    if not q or len(q) < 2:
        return jsonify({"ok": True, "items": []})

    like = f"%{q}%"

    # Build query based on view_type
    query = Item.query.filter_by(user_id=current_user.id)

    # Filter by view type
    if view_type == "active":
        query = query.filter(Item.is_active == True)
    elif view_type == "ended":
        query = query.filter(Item.is_active == False)
    # sold items are handled separately via Sales table

    # Search in title, SKU, or supplier
    query = query.filter(
        or_(
            Item.title.ilike(like),
            Item.sku.ilike(like),
            Item.supplier.ilike(like)
        )
    )

    items = query.order_by(Item.updated_at.desc()).limit(10).all()

    results = []
    for it in items:
        results.append({
            "id": it.id,
            "title": it.title,
            "sku": it.sku,
            "cost": float(it.item_cost) if it.item_cost is not None else None,
            "price": float(it.item_price) if it.item_price is not None else None,
            "supplier": it.supplier,
            "location_code": it.location_code
        })

    return jsonify({"ok": True, "items": results})


# ==================== AI Research ====================
@main_bp.route("/ai-research")
@login_required
def ai_research():
    """AI Research standalone page"""
    return render_template("ai_research.html")


@main_bp.route("/api/ai-research", methods=["POST"])
@login_required
def api_ai_research():
    """
    AI-powered eBay market research using OpenAI API
    Expects JSON: {item_id: int} or {title: str, condition: str, notes: str}
    """
    import sys
    import traceback

    print("=" * 80, file=sys.stderr)
    print("AI RESEARCH API CALLED", file=sys.stderr)
    print("=" * 80, file=sys.stderr)

    try:
        from openai import OpenAI
        print("✓ OpenAI imported successfully", file=sys.stderr)
    except Exception as e:
        print(f"✗ Failed to import OpenAI: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return jsonify({
            "ok": False,
            "error": f"Failed to import OpenAI library: {str(e)}"
        }), 500

    # Get OpenAI API key from environment
    openai_api_key = os.environ.get("OPENAI_API_KEY")
    print(f"API Key present: {bool(openai_api_key)}", file=sys.stderr)
    if not openai_api_key:
        print("✗ No OpenAI API key found", file=sys.stderr)
        return jsonify({
            "ok": False,
            "error": "OpenAI API key not configured. Please add OPENAI_API_KEY to your .env file."
        }), 500

    try:
        client = OpenAI(api_key=openai_api_key)
        print("✓ OpenAI client created", file=sys.stderr)
    except Exception as e:
        print(f"✗ Failed to create OpenAI client: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return jsonify({
            "ok": False,
            "error": f"Failed to initialize OpenAI client: {str(e)}"
        }), 500

    try:
        data = request.get_json() or {}
        print(f"Request data: {data}", file=sys.stderr)
    except Exception as e:
        print(f"✗ Failed to parse JSON: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return jsonify({
            "ok": False,
            "error": f"Invalid JSON in request: {str(e)}"
        }), 400

    # Get item data either from item_id or direct input
    item_id = data.get("item_id")
    print(f"Item ID: {item_id}", file=sys.stderr)

    if item_id:
        try:
            item = Item.query.filter_by(id=item_id, user_id=current_user.id).first()
            if not item:
                print(f"✗ Item {item_id} not found", file=sys.stderr)
                return jsonify({"ok": False, "error": "Item not found"}), 404

            item_title = item.title
            # Use supplier info as notes if available
            condition = "Used"
            notes = f"Supplier: {item.supplier}" if item.supplier else ""
            if item.item_cost:
                notes += f" | Cost: ${item.item_cost}"
            print(f"✓ Item found: {item_title}", file=sys.stderr)
        except Exception as e:
            print(f"✗ Database error: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            return jsonify({"ok": False, "error": f"Database error: {str(e)}"}), 500
    else:
        item_title = data.get("title", "").strip()
        condition = data.get("condition", "Used")
        notes = data.get("notes", "")
        print(f"✓ Direct input: {item_title}", file=sys.stderr)

    if not item_title:
        print("✗ No item title provided", file=sys.stderr)
        return jsonify({"ok": False, "error": "Item title is required"}), 400

    # Get market settings from user input or defaults
    market_region = data.get("market_region") or "US"
    currency = data.get("currency") or "USD"
    print(f"Market: {market_region}, Currency: {currency}", file=sys.stderr)

    # STEP 1: Scrape real eBay sold listings
    print("📡 Scraping eBay sold listings...", file=sys.stderr)
    from qventory.helpers.ebay_scraper import scrape_ebay_sold_listings, format_listings_for_ai

    scraped_data = scrape_ebay_sold_listings(item_title, max_results=10)
    print(f"✓ Scraped {scraped_data.get('count', 0)} listings", file=sys.stderr)

    # Format scraped data for AI
    real_market_data = format_listings_for_ai(scraped_data)
    ebay_search_url = scraped_data.get('url', '')

    # Build the prompt with REAL data
    system_prompt = """You are an eBay pricing analyst. You MUST respond with ONLY pure HTML code.
NO explanations, NO markdown, NO code blocks - just raw HTML starting with <div."""

    user_prompt = f"""Analyze REAL eBay sold listings data for: {item_title}
Condition: {condition}
Market: {market_region}

REAL SOLD LISTINGS DATA:
{real_market_data}

Based on this REAL market data above, provide:
1. Accurate pricing strategy
2. Title optimization tips based on what's actually selling
3. Market insights from the real data

RESPOND WITH ONLY THIS HTML (no ```html, no explanations):

<div style="font-family:system-ui;line-height:1.5;color:#e8e8e8;font-size:13px">
  <div style="background:#1a1d24;padding:10px;border-radius:6px;margin-bottom:10px">
    <div style="color:#9ca3af;font-size:12px;margin-bottom:6px">📊 Market Analysis</div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
      <div><span style="color:#60a5fa">●</span> Price Range: ${currency}XX-XX</div>
      <div><span style="color:#60a5fa">●</span> Average: ${currency}XX</div>
    </div>
  </div>

  <div style="background:#1a1d24;padding:10px;border-radius:6px;margin-bottom:10px">
    <div style="color:#9ca3af;font-size:12px;margin-bottom:6px">💰 Pricing Strategy</div>
    <div style="margin-bottom:4px"><strong style="color:#34d399">List Price:</strong> ${currency}XX.XX</div>
    <div style="margin-bottom:4px"><strong style="color:#fbbf24">Minimum Accept:</strong> ${currency}XX.XX</div>
    <div style="margin-bottom:6px"><strong style="color:#f87171">Auto-Decline:</strong> Below ${currency}XX</div>
    <div style="color:#9ca3af;font-size:11px">💡 Format: BIN + Best Offer | Shipping: [Free/Calculated based on trends]</div>
  </div>

  <div style="background:#1a1d24;padding:10px;border-radius:6px;margin-bottom:10px">
    <div style="color:#9ca3af;font-size:12px;margin-bottom:6px">✨ Title Optimization</div>
    <div style="font-size:11px;color:#e8e8e8;line-height:1.6">
      <div style="margin-bottom:4px"><strong style="color:#34d399">Keywords found in sold listings:</strong></div>
      <div style="color:#9ca3af">• [Analyze real titles and list common keywords/patterns]</div>
      <div style="margin-top:6px"><strong style="color:#fbbf24">Suggested title format:</strong></div>
      <div style="color:#9ca3af">[Brand] [Model] [Key Specs] [Condition] - [Unique Features]</div>
    </div>
  </div>

  <div style="background:#1a1d24;padding:10px;border-radius:6px">
    <div style="color:#9ca3af;font-size:12px;margin-bottom:6px">📝 Market Insights</div>
    <div style="font-size:11px;color:#9ca3af;line-height:1.5">[2-3 sentences analyzing the market: what's selling, at what prices, and why. Include specific observations from the real data.]</div>
    <div style="margin-top:8px;padding:6px;background:#0f1115;border-radius:4px;font-size:10px;color:#6b7280">
      ✅ Based on {len(scraped_data.get('items', []))} real sold listings | <a href="{ebay_search_url}" target="_blank" style="color:#60a5fa;text-decoration:none">View on eBay ↗</a>
    </div>
  </div>
</div>

CRITICAL RULES:
1. Calculate actual average/range from the REAL sold prices above
2. Start response IMMEDIATELY with <div (no text before)
3. NO markdown code fences (```)
4. NO explanations or text outside HTML
5. Keep total under 80 words
6. Use ONLY the real prices from the data - don't invent numbers
7. The search link is pre-filled - keep it as-is"""

    print("Building prompts...", file=sys.stderr)
    print(f"System prompt length: {len(system_prompt)} chars", file=sys.stderr)
    print(f"User prompt length: {len(user_prompt)} chars", file=sys.stderr)

    try:
        print("Calling OpenAI API...", file=sys.stderr)
        response = client.chat.completions.create(
            model="gpt-4-turbo-preview",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3,
            max_tokens=2000
        )

        print("✓ OpenAI API call successful", file=sys.stderr)
        result = response.choices[0].message.content
        print(f"Result length: {len(result)} chars", file=sys.stderr)

        # Clean up the response - remove markdown code blocks if present
        result = result.strip()
        if result.startswith("```html"):
            result = result[7:]  # Remove ```html
        if result.startswith("```"):
            result = result[3:]  # Remove ```
        if result.endswith("```"):
            result = result[:-3]  # Remove trailing ```
        result = result.strip()

        print(f"Cleaned result (first 200 chars): {result[:200]}", file=sys.stderr)
        print("=" * 80, file=sys.stderr)

        # Get top 3 examples for transparency
        example_listings = []
        for item in scraped_data.get('items', [])[:3]:
            example_listings.append({
                'title': item['title'],
                'price': item['price'],
                'link': item['link']
            })

        return jsonify({
            "ok": True,
            "result": result,
            "item_title": item_title,
            "scraped_count": scraped_data.get('count', 0),
            "examples": example_listings
        })

    except Exception as e:
        print(f"✗ OpenAI API error: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        print("=" * 80, file=sys.stderr)
        return jsonify({
            "ok": False,
            "error": f"OpenAI API error: {str(e)}"
        }), 500


# ==================== NOTIFICATIONS API ====================

@main_bp.route("/api/notifications/unread")
@login_required
def get_unread_notifications():
    """Get unread notifications for current user"""
    from qventory.models.notification import Notification

    notifications = Notification.get_recent(current_user.id, limit=10, include_read=False)
    unread_count = Notification.get_unread_count(current_user.id)

    return jsonify({
        "ok": True,
        "notifications": [n.to_dict() for n in notifications],
        "unread_count": unread_count
    })


@main_bp.route("/api/notifications/<int:notification_id>/read", methods=["POST"])
@login_required
def mark_notification_read(notification_id):
    """Mark a notification as read"""
    from qventory.models.notification import Notification

    notification = Notification.query.filter_by(
        id=notification_id,
        user_id=current_user.id
    ).first()

    if not notification:
        return jsonify({"ok": False, "error": "Notification not found"}), 404

    notification.mark_as_read()

    return jsonify({"ok": True})


@main_bp.route("/api/notifications/mark-all-read", methods=["POST"])
@login_required
def mark_all_notifications_read():
    """Mark all notifications as read for current user"""
    from qventory.models.notification import Notification

    Notification.mark_all_as_read(current_user.id)

    return jsonify({"ok": True})


# ==================== LIBERIS LOAN MANAGEMENT ====================

@main_bp.route("/expenses/liberis-loan", methods=["GET", "POST"])
@login_required
def liberis_loan_settings():
    """Manage Liberis loan (eBay Seller Capital)"""
    from qventory.models.liberis_loan import LiberisLoan
    from datetime import datetime

    active_loan = LiberisLoan.get_active_loan(current_user.id)

    if request.method == "POST":
        action = request.form.get("action")

        if action == "create":
            try:
                percentage = float(request.form.get("percentage", 0))
                start_date_str = request.form.get("start_date", "").strip()
                total_amount = float(request.form.get("total_amount", 0))

                # Validate inputs
                if percentage <= 0 or percentage > 100:
                    flash("Percentage must be between 0 and 100", "error")
                    return redirect(url_for("main.liberis_loan_settings"))

                if total_amount <= 0:
                    flash("Total amount must be greater than 0", "error")
                    return redirect(url_for("main.liberis_loan_settings"))

                if not start_date_str:
                    flash("Start date is required", "error")
                    return redirect(url_for("main.liberis_loan_settings"))

                start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()

                # Create loan
                loan = LiberisLoan.create_loan(
                    user_id=current_user.id,
                    percentage=percentage,
                    start_date=start_date,
                    total_amount=total_amount
                )

                flash(f"Liberis loan created. {loan.percentage}% will be deducted from sales starting {loan.start_date.strftime('%b %d, %Y')}", "ok")
                return redirect(url_for("main.liberis_loan_settings"))

            except ValueError as e:
                flash(f"Invalid input: {str(e)}", "error")
                return redirect(url_for("main.liberis_loan_settings"))

        elif action == "deactivate":
            if active_loan:
                active_loan.is_active = False
                active_loan.updated_at = datetime.utcnow()
                db.session.commit()
                flash("Liberis loan deactivated. Fees will no longer be applied to new sales.", "ok")
            return redirect(url_for("main.liberis_loan_settings"))

        elif action == "recalculate":
            if active_loan:
                active_loan.recalculate_paid_amount()
                flash("Loan payment recalculated based on all sales since start date.", "ok")
            return redirect(url_for("main.liberis_loan_settings"))

    # Get all loans (active and historical)
    all_loans = LiberisLoan.query.filter_by(user_id=current_user.id).order_by(LiberisLoan.created_at.desc()).all()

    return render_template("liberis_loan_settings.html",
                         active_loan=active_loan,
                         all_loans=all_loans)
