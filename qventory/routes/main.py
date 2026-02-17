from flask import (
    render_template, request, redirect, url_for, send_file, flash, Response,
    jsonify, send_from_directory, make_response, current_app, abort, session
)
from flask_login import login_required, current_user, login_user, logout_user
from sqlalchemy import func, or_, case
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
import stripe
import uuid


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
from ..models.subscription import Subscription
from ..models.help_article import HelpArticle
from ..models.support import SupportTicket, SupportMessage, SupportAttachment
from ..helpers.help_center import seed_help_articles, render_help_markdown
from ..helpers import (
    get_or_create_settings, generate_sku, compose_location_code,
    parse_location_code, parse_values, human_from_code, qr_label_image
)
from . import main_bp
from ..helpers.inventory_queries import (
    fetch_active_items,
    fetch_inactive_by_user_items,
    fetch_sold_items,
    fetch_ended_items,
    fetch_fulfillment_orders,
    detect_thumbnail_mismatches,
    detect_sale_title_mismatches,
)
from ..models.sale import Sale
from ..models.item_cost_history import ItemCostHistory
from ..models.expense import Expense
from ..models.receipt_item import ReceiptItem
from ..models.auto_relist_rule import AutoRelistHistory
from ..models.ebay_category import EbayCategory
from ..models.profit_calculator_report import ProfitCalculatorReport
from ..models.ebay_fee_rule import EbayFeeRule

PAGE_SIZES = [10, 20, 50, 100, 500]

# ==================== Cloudinary ====================
# pip install cloudinary
CLOUDINARY_CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME")
CLOUDINARY_API_KEY = os.environ.get("CLOUDINARY_API_KEY")
CLOUDINARY_API_SECRET = os.environ.get("CLOUDINARY_API_SECRET")
CLOUDINARY_UPLOAD_FOLDER = os.environ.get("CLOUDINARY_UPLOAD_FOLDER", "qventory/items")
CLOUDINARY_STORE_FOLDER = os.environ.get("CLOUDINARY_STORE_FOLDER", "qventory/stores")
CLOUDINARY_SUPPORT_FOLDER = os.environ.get("CLOUDINARY_SUPPORT_FOLDER", "qventory/support")
EBAY_VERIFICATION_TOKEN = os.environ.get("EBAY_VERIFICATION_TOKEN", "")
EBAY_DELETIONS_ENDPOINT_URL = os.environ.get("EBAY_DELETIONS_ENDPOINT_URL", "")

# Stripe
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")
STRIPE_PRICE_PREMIUM = os.environ.get("STRIPE_PRICE_PREMIUM")
STRIPE_PRICE_PLUS = os.environ.get("STRIPE_PRICE_PLUS")
STRIPE_PRICE_PRO = os.environ.get("STRIPE_PRICE_PRO")
if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY


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


# ---------------------- Landing pública ----------------------

@main_bp.route("/")
def landing():
    return render_template("landing.html")


@main_bp.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():
    if not STRIPE_WEBHOOK_SECRET:
        return Response("Webhook secret not configured", status=500)

    payload = request.data
    sig_header = request.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        return Response("Invalid payload", status=400)
    except stripe.error.SignatureVerificationError:
        return Response("Invalid signature", status=400)

    event_type = event.get("type")
    data_object = event.get("data", {}).get("object", {})

    if event_type == "checkout.session.completed":
        subscription_id = data_object.get("subscription")
        customer_id = data_object.get("customer")
        metadata = data_object.get("metadata") or {}
        plan_name = metadata.get("plan")
        user_id = metadata.get("user_id")
        customer_email = (data_object.get("customer_details") or {}).get("email")

        if subscription_id:
            subscription = Subscription.query.filter_by(
                stripe_subscription_id=subscription_id
            ).first()
            if not subscription and user_id:
                try:
                    user = User.query.filter_by(id=int(user_id)).first()
                except (TypeError, ValueError):
                    user = None
                if user:
                    subscription = Subscription.query.filter_by(user_id=user.id).first()
            if not subscription and customer_email:
                user = User.query.filter_by(email=customer_email).first()
                if user:
                    subscription = Subscription.query.filter_by(user_id=user.id).first()

            if subscription:
                old_plan = subscription.plan
                subscription.stripe_customer_id = customer_id
                subscription.stripe_subscription_id = subscription_id
                if plan_name:
                    subscription.plan = plan_name
                subscription.status = "active"
                subscription.updated_at = datetime.utcnow()
                if plan_name:
                    _sync_user_role_from_plan(subscription.user, plan_name, allow_downgrade=False)
                    if old_plan == "free" and plan_name != "free":
                        _reactivate_items_after_upgrade(subscription.user_id)
                        from qventory.models.marketplace_credential import MarketplaceCredential
                        ebay_cred = MarketplaceCredential.query.filter_by(
                            user_id=subscription.user_id,
                            marketplace='ebay',
                            is_active=True
                        ).first()
                        if ebay_cred:
                            from qventory.tasks import import_ebay_inventory
                            import_ebay_inventory.delay(subscription.user_id, import_mode='new_only', listing_status='ACTIVE')
                db.session.commit()
                if plan_name and old_plan != plan_name:
                    try:
                        from qventory.helpers.email_sender import send_plan_upgrade_email
                        send_plan_upgrade_email(subscription.user.email, subscription.user.username, plan_name)
                    except Exception:
                        pass

    elif event_type == "customer.subscription.updated":
        subscription_id = data_object.get("id")
        price_id = None
        items = data_object.get("items", {}).get("data", [])
        if items:
            price_id = items[0].get("price", {}).get("id")
        plan_name = _plan_from_stripe_price(price_id)
        raw_status = data_object.get("status")
        cancel_at_period_end = data_object.get("cancel_at_period_end")
        status = None
        if raw_status in {"active", "trialing"}:
            status = "active"
        elif raw_status in {"past_due", "unpaid"}:
            status = "suspended"
        elif raw_status in {"canceled", "incomplete_expired"}:
            status = "cancelled"
        elif raw_status:
            status = raw_status
        period_end = data_object.get("current_period_end")
        trial_end = data_object.get("trial_end")

        subscription = Subscription.query.filter_by(
            stripe_subscription_id=subscription_id
        ).first()
        if subscription:
            now = datetime.utcnow()
            old_plan = subscription.plan
            if plan_name:
                subscription.plan = plan_name
            if period_end:
                subscription.current_period_end = datetime.utcfromtimestamp(period_end)
            if trial_end:
                subscription.trial_ends_at = datetime.utcfromtimestamp(trial_end)
                subscription.on_trial = raw_status == "trialing"
            subscription.updated_at = datetime.utcnow()
            if raw_status == "trialing":
                subscription.user.has_used_trial = True
            if plan_name:
                _sync_user_role_from_plan(subscription.user, plan_name, allow_downgrade=False)
                if old_plan == "free" and plan_name != "free":
                    _reactivate_items_after_upgrade(subscription.user_id)
                    from qventory.models.marketplace_credential import MarketplaceCredential
                    ebay_cred = MarketplaceCredential.query.filter_by(
                        user_id=subscription.user_id,
                        marketplace='ebay',
                        is_active=True
                    ).first()
                    if ebay_cred:
                        from qventory.tasks import import_ebay_inventory
                        import_ebay_inventory.delay(subscription.user_id, import_mode='new_only', listing_status='ACTIVE')
            if status:
                subscription.status = status
            if cancel_at_period_end and status in {"active", "suspended"}:
                subscription.cancelled_at = now
            if status == "cancelled":
                if raw_status == "trialing":
                    _downgrade_to_free_and_enforce(subscription.user, subscription, now)
                elif subscription.current_period_end and subscription.current_period_end > now:
                    subscription.status = "active"
                    subscription.cancelled_at = now
                else:
                    _downgrade_to_free_and_enforce(subscription.user, subscription, now)
            db.session.commit()

            if plan_name and old_plan != plan_name:
                try:
                    from qventory.helpers.email_sender import send_plan_upgrade_email
                    send_plan_upgrade_email(subscription.user.email, subscription.user.username, plan_name)
                except Exception:
                    pass

            if cancel_at_period_end and raw_status == "trialing" and trial_end:
                now = datetime.utcnow()
                if datetime.utcfromtimestamp(trial_end) > now:
                    try:
                        stripe.Subscription.delete(subscription_id)
                    except Exception as exc:
                        current_app.logger.exception("Stripe trial cancel failed: %s", exc)
                    deleted_count = _downgrade_to_free_and_enforce(subscription.user, subscription, now)
                    db.session.commit()
                    current_app.logger.warning(
                        "Trial cancelled immediately for user %s; removed %s items to meet Free plan limit.",
                        subscription.user_id,
                        deleted_count,
                    )

    elif event_type == "customer.subscription.deleted":
        subscription_id = data_object.get("id")
        subscription = Subscription.query.filter_by(
            stripe_subscription_id=subscription_id
        ).first()
        if subscription:
            was_cancelled = subscription.cancelled_at is not None
            now = datetime.utcnow()
            _downgrade_to_free_and_enforce(subscription.user, subscription, now)
            db.session.commit()
            if not was_cancelled:
                try:
                    from qventory.helpers.email_sender import send_plan_cancellation_email
                    send_plan_cancellation_email(subscription.user.email, subscription.user.username)
                except Exception:
                    pass

    elif event_type == "invoice.paid":
        subscription_id = data_object.get("subscription")
        period_end = data_object.get("lines", {}).get("data", [])
        subscription = Subscription.query.filter_by(
            stripe_subscription_id=subscription_id
        ).first()
        if subscription:
            if period_end:
                end_ts = period_end[0].get("period", {}).get("end")
                if end_ts:
                    subscription.current_period_end = datetime.utcfromtimestamp(end_ts)
            subscription.status = "active"
            subscription.updated_at = datetime.utcnow()
            db.session.commit()

    elif event_type == "invoice.payment_failed":
        subscription_id = data_object.get("subscription")
        subscription = Subscription.query.filter_by(
            stripe_subscription_id=subscription_id
        ).first()
        if subscription:
            subscription.status = "suspended"
            subscription.updated_at = datetime.utcnow()
            db.session.commit()

    return Response(status=200)


def _sync_user_role_from_plan(user, plan_name: str | None, *, allow_downgrade: bool = False) -> None:
    if not user or not plan_name:
        return
    if plan_name in {"god", "early_adopter"}:
        return
    if user.role in {"god", "early_adopter"}:
        return
    if plan_name == "free" and not allow_downgrade:
        return
    if user.role != plan_name:
        user.role = plan_name


@main_bp.route("/stripe/checkout", methods=["POST"])
@login_required
def stripe_checkout():
    if not STRIPE_SECRET_KEY:
        flash("Stripe is not configured yet.", "error")
        return redirect(url_for("main.upgrade"))

    plan_name = request.form.get("plan", "").strip().lower()
    if plan_name not in {"premium", "plus", "pro"}:
        flash("Selected plan is not available for checkout.", "error")
        return redirect(url_for("main.upgrade"))

    current_plan = current_user.get_subscription().plan
    if plan_name == current_plan:
        flash("You are already on that plan.", "info")
        return redirect(url_for("main.upgrade"))

    return _start_stripe_checkout(plan_name, success_redirect="main.upgrade", cancel_redirect="main.upgrade")


@main_bp.route("/stripe/checkout/start/<plan_name>")
@login_required
def stripe_checkout_start(plan_name):
    plan_name = (plan_name or "").strip().lower()
    if plan_name not in {"premium", "plus", "pro"}:
        flash("Selected plan is not available for checkout.", "error")
        return redirect(url_for("main.pricing"))

    current_plan = current_user.get_subscription().plan
    if plan_name == current_plan:
        flash("You are already on that plan.", "info")
        return redirect(url_for("main.upgrade"))

    return _start_stripe_checkout(plan_name, success_redirect="main.upgrade", cancel_redirect="main.pricing")


@main_bp.route("/stripe/cancel-subscription", methods=["POST"])
@login_required
def stripe_cancel_subscription():
    if not STRIPE_SECRET_KEY:
        flash("Stripe is not configured yet.", "error")
        return redirect(url_for("main.settings"))

    subscription = current_user.get_subscription()
    if not subscription or not subscription.stripe_subscription_id:
        flash("No active Stripe subscription found for this account.", "info")
        return redirect(url_for("main.settings"))

    try:
        stripe_sub = stripe.Subscription.retrieve(subscription.stripe_subscription_id)
        now = datetime.utcnow()
        trial_end_ts = stripe_sub.get("trial_end")
        is_trialing = stripe_sub.get("status") == "trialing"
        trial_active = False
        if is_trialing and trial_end_ts:
            trial_active = datetime.utcfromtimestamp(trial_end_ts) > now

        if trial_active:
            stripe.Subscription.delete(subscription.stripe_subscription_id)
            deleted_count = _downgrade_to_free_and_enforce(current_user, subscription, now)
            db.session.commit()
            message = "Trial cancelled. Your plan is now Free."
            if deleted_count:
                message += f" {deleted_count} item(s) were removed to fit the Free plan limit."
            try:
                from qventory.helpers.email_sender import send_plan_cancellation_email
                send_plan_cancellation_email(current_user.email, current_user.username)
            except Exception:
                pass
            flash(message, "ok")
        else:
            stripe.Subscription.modify(
                subscription.stripe_subscription_id,
                cancel_at_period_end=True
            )
            subscription.cancelled_at = now
            subscription.updated_at = now
            db.session.commit()
            try:
                from qventory.helpers.email_sender import send_plan_cancellation_email
                send_plan_cancellation_email(current_user.email, current_user.username)
            except Exception:
                pass
            flash("Cancellation scheduled. You will keep access until the current period ends.", "ok")
    except Exception as exc:
        current_app.logger.exception("Stripe cancel failed: %s", exc)
        flash("Unable to cancel subscription right now. Please try again.", "error")

    return redirect(url_for("main.settings"))


@main_bp.route("/stripe/customer-portal", methods=["POST"])
@login_required
def stripe_customer_portal():
    if not STRIPE_SECRET_KEY:
        flash("Stripe is not configured yet.", "error")
        return redirect(url_for("main.settings"))

    subscription = current_user.get_subscription()
    if not subscription:
        flash("No subscription found for this account.", "info")
        return redirect(url_for("main.settings"))

    customer_id = subscription.stripe_customer_id
    if not customer_id and subscription.stripe_subscription_id:
        try:
            stripe_sub = stripe.Subscription.retrieve(subscription.stripe_subscription_id)
            customer_id = stripe_sub.get("customer")
            if customer_id:
                subscription.stripe_customer_id = customer_id
                subscription.updated_at = datetime.utcnow()
                db.session.commit()
        except Exception as exc:
            current_app.logger.exception("Stripe subscription lookup failed: %s", exc)

    if not customer_id:
        flash("No Stripe customer found for this account yet.", "info")
        return redirect(url_for("main.settings"))

    try:
        portal_session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=url_for("main.settings", _external=True)
        )
    except Exception as exc:
        current_app.logger.exception("Stripe portal failed: %s", exc)
        flash("Unable to open the billing portal right now.", "error")
        return redirect(url_for("main.settings"))

    return redirect(portal_session.url, code=303)


def _plan_from_stripe_price(price_id: str | None) -> str | None:
    if not price_id:
        return None
    mapping = {
        STRIPE_PRICE_PREMIUM: "premium",
        STRIPE_PRICE_PLUS: "plus",
        STRIPE_PRICE_PRO: "pro",
    }
    return mapping.get(price_id)


def _stripe_price_for_plan(plan_name: str | None) -> str | None:
    if not plan_name:
        return None
    mapping = {
        "premium": STRIPE_PRICE_PREMIUM,
        "plus": STRIPE_PRICE_PLUS,
        "pro": STRIPE_PRICE_PRO,
    }
    return mapping.get(plan_name)


def _refresh_subscription_from_stripe(subscription: Subscription):
    if not subscription or not STRIPE_SECRET_KEY or not subscription.stripe_subscription_id:
        return subscription

    try:
        stripe_sub = stripe.Subscription.retrieve(subscription.stripe_subscription_id)
    except Exception as exc:
        current_app.logger.exception("Stripe subscription refresh failed: %s", exc)
        return subscription

    now = datetime.utcnow()
    raw_status = stripe_sub.get("status")
    cancel_at_period_end = stripe_sub.get("cancel_at_period_end")
    canceled_at = stripe_sub.get("canceled_at")
    period_end_ts = stripe_sub.get("current_period_end")
    trial_end_ts = stripe_sub.get("trial_end")
    items = stripe_sub.get("items", {}).get("data", [])
    price_id = items[0].get("price", {}).get("id") if items else None
    plan_name = _plan_from_stripe_price(price_id)

    status = None
    if raw_status in {"active", "trialing"}:
        status = "active"
    elif raw_status in {"past_due", "unpaid"}:
        status = "suspended"
    elif raw_status in {"canceled", "incomplete_expired"}:
        status = "cancelled"
    elif raw_status:
        status = raw_status

    dirty = False

    if plan_name and subscription.plan != plan_name:
        subscription.plan = plan_name
        dirty = True

    if period_end_ts:
        new_end = datetime.utcfromtimestamp(period_end_ts)
        if subscription.current_period_end != new_end:
            subscription.current_period_end = new_end
            dirty = True

    if trial_end_ts:
        new_trial_end = datetime.utcfromtimestamp(trial_end_ts)
        if subscription.trial_ends_at != new_trial_end:
            subscription.trial_ends_at = new_trial_end
            dirty = True

    on_trial = raw_status == "trialing"
    if subscription.on_trial != on_trial:
        subscription.on_trial = on_trial
        dirty = True

    if raw_status == "trialing" and not subscription.user.has_used_trial:
        subscription.user.has_used_trial = True
        dirty = True

    if status == "cancelled":
        if subscription.current_period_end and subscription.current_period_end > now:
            status = "active"
        else:
            subscription.on_trial = False
            subscription.trial_ends_at = None
            subscription.current_period_end = None
            dirty = True

    if status and subscription.status != status:
        subscription.status = status
        dirty = True

    if cancel_at_period_end and not subscription.cancelled_at:
        if canceled_at:
            subscription.cancelled_at = datetime.utcfromtimestamp(canceled_at)
        else:
            subscription.cancelled_at = now
        dirty = True

    if dirty:
        subscription.updated_at = now
        db.session.commit()

    return subscription


def _start_stripe_checkout(plan_name, success_redirect, cancel_redirect):
    price_id = _stripe_price_for_plan(plan_name)
    if not price_id:
        flash("Stripe price is not configured for that plan.", "error")
        return redirect(url_for(success_redirect))

    from qventory.models.system_setting import SystemSetting

    trial_days = SystemSetting.get_int('stripe_trial_days', 10)
    metadata = {
        "plan": plan_name,
        "user_id": str(current_user.id),
    }

    try:
        session_params = {
            "mode": "subscription",
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": url_for(success_redirect, stripe="success", _external=True),
            "cancel_url": url_for(cancel_redirect, stripe="cancel", _external=True),
            "customer_email": current_user.email,
            "client_reference_id": str(current_user.id),
            "metadata": metadata,
            "allow_promotion_codes": True,
        }
        subscription_data = {"metadata": metadata}
        if trial_days and trial_days > 0 and not current_user.has_used_trial:
            subscription_data["trial_period_days"] = int(trial_days)
        if subscription_data:
            session_params["subscription_data"] = subscription_data

        checkout_session = stripe.checkout.Session.create(**session_params)
    except Exception as exc:
        current_app.logger.exception("Stripe checkout failed: %s", exc)
        flash("Stripe checkout failed. Please try again.", "error")
        return redirect(url_for(success_redirect))

    return redirect(checkout_session.url, code=303)


def _enforce_free_plan_limit(user_id: int) -> int:
    from qventory.models.subscription import PlanLimit

    free_limits = PlanLimit.query.filter_by(plan='free').first()
    if not free_limits or free_limits.max_items is None:
        return 0

    active_items = Item.query.filter(
        Item.user_id == user_id,
        Item.is_active.is_(True),
        Item.inactive_by_user.is_(False)
    ).count()
    over_limit = active_items - free_limits.max_items
    if over_limit <= 0:
        return 0

    items_to_deactivate = (
        Item.query.filter(
            Item.user_id == user_id,
            Item.is_active.is_(True),
            Item.inactive_by_user.is_(False)
        )
        .order_by(Item.created_at.asc())
        .limit(over_limit)
        .all()
    )
    tag = "[FREE_PLAN_LIMIT_DEACTIVATED]"
    for item in items_to_deactivate:
        item.is_active = False
        notes = item.notes or ""
        if tag not in notes:
            timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
            marker = f"\n[{timestamp}] {tag}"
            item.notes = (notes + marker).strip()

    return len(items_to_deactivate)


def _downgrade_to_free_and_enforce(user: User, subscription: Subscription, now: datetime) -> int:
    subscription.plan = "free"
    subscription.status = "cancelled"
    subscription.on_trial = False
    subscription.trial_ends_at = None
    subscription.cancelled_at = now
    subscription.ended_at = now
    subscription.current_period_end = None
    subscription.updated_at = now

    _sync_user_role_from_plan(user, "free", allow_downgrade=True)
    deleted_count = _enforce_free_plan_limit(user.id)
    return deleted_count


def _reactivate_items_after_upgrade(user_id: int) -> int:
    tag = "[FREE_PLAN_LIMIT_DEACTIVATED]"
    items = Item.query.filter(
        Item.user_id == user_id,
        Item.is_active.is_(False),
        Item.sold_at.is_(None),
        Item.notes.ilike(f"%{tag}%")
    ).all()
    if not items:
        return 0

    for item in items:
        item.is_active = True
        if item.notes:
            cleaned = "\n".join(
                line for line in item.notes.splitlines() if tag not in line
            ).strip()
            item.notes = cleaned or None

    return len(items)


# ---------------------- Help Center (public) ----------------------

@main_bp.route("/help")
@login_required
def help_center_index():
    seed_help_articles()
    articles = HelpArticle.query.filter_by(is_published=True)\
        .order_by(HelpArticle.display_order.asc(), HelpArticle.title.asc())\
        .all()
    return render_template("help_center.html", articles=articles)


@main_bp.route("/help/<slug>")
@login_required
def help_center_article(slug):
    seed_help_articles()
    article = HelpArticle.query.filter_by(slug=slug, is_published=True).first_or_404()
    rendered = render_help_markdown(article.body_md)
    articles = HelpArticle.query.filter_by(is_published=True)\
        .order_by(HelpArticle.display_order.asc(), HelpArticle.title.asc())\
        .all()
    return render_template(
        "help_article.html",
        article=article,
        rendered=rendered,
        articles=articles,
    )


# ---------------------- Dashboard (protegido) ----------------------

def _normalize_arg(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


SUPPORT_ROLES = {"early_adopter", "premium", "plus", "pro", "god"}


def _support_access_allowed(user: User) -> bool:
    return user is not None and user.role in SUPPORT_ROLES


def _support_broadcast_exists(user_id: int) -> bool:
    return SupportTicket.query.filter_by(user_id=user_id, kind="broadcast").count() > 0


def _support_open_count(user_id: int) -> int:
    return SupportTicket.query.filter(
        SupportTicket.user_id == user_id,
        SupportTicket.status == "open",
        SupportTicket.kind != "broadcast",
    ).count()


def _support_ticket_code() -> str:
    code = SupportTicket.generate_ticket_code()
    while SupportTicket.query.filter_by(ticket_code=code).first() is not None:
        code = SupportTicket.generate_ticket_code()
    return code


def _support_unread_for_user(user_id: int) -> int:
    return (
        db.session.query(func.count(func.distinct(SupportMessage.ticket_id)))
        .join(SupportTicket, SupportTicket.id == SupportMessage.ticket_id)
        .filter(
            SupportTicket.user_id == user_id,
            SupportMessage.sender_role == "admin",
            SupportMessage.is_read_by_user.is_(False),
        )
        .scalar()
    )


def _support_unread_for_admin() -> int:
    return (
        db.session.query(func.count(func.distinct(SupportMessage.ticket_id)))
        .join(SupportTicket, SupportTicket.id == SupportMessage.ticket_id)
        .filter(
            SupportTicket.status == "open",
            SupportMessage.sender_role == "user",
            SupportMessage.is_read_by_admin.is_(False),
        )
        .scalar()
    )


def _upload_support_attachments(files, *, user_id: int, ticket_code: str):
    if not cloudinary_enabled:
        return [], "Cloudinary not configured"
    if not files:
        return [], None
    files = [f for f in files if f and getattr(f, "filename", "")]
    if not files:
        return [], None
    if len(files) > 3:
        return [], "You can upload up to 3 images."

    uploads = []
    for file in files:
        if not file or not getattr(file, "filename", ""):
            continue
        if not (file.mimetype or "").startswith("image/"):
            return [], "Only image files are allowed."
        file.stream.seek(0, os.SEEK_END)
        size = file.stream.tell()
        file.stream.seek(0)
        if size > 2 * 1024 * 1024:
            return [], "Each image must be 2MB or less."

        up = cloudinary.uploader.upload(
            file,
            folder=f"{CLOUDINARY_SUPPORT_FOLDER}/{user_id}/{ticket_code}",
            resource_type="image",
        )
        uploads.append({
            "url": up.get("secure_url"),
            "public_id": up.get("public_id"),
            "bytes": up.get("bytes"),
            "filename": file.filename,
        })

    return uploads, None


def _get_inventory_filter_params():
    missing_data = _normalize_arg(request.args.get("missing_data"))
    if missing_data is None:
        if _normalize_arg(request.args.get("missing_cost")):
            missing_data = "cost"
        elif _normalize_arg(request.args.get("missing_supplier")):
            missing_data = "supplier"
    return {
        "search": _normalize_arg(request.args.get("q")),
        "A": _normalize_arg(request.args.get("A")),
        "B": _normalize_arg(request.args.get("B")),
        "S": _normalize_arg(request.args.get("S")),
        "C": _normalize_arg(request.args.get("C")),
        "platform": _normalize_arg(request.args.get("platform")),
        "missing_data": missing_data,
    }


def _get_inventory_sort_params():
    sort_by = _normalize_arg(request.args.get("sort"))
    sort_dir = _normalize_arg(request.args.get("dir"))
    if sort_dir and sort_dir.lower() not in {"asc", "desc"}:
        sort_dir = None
    return sort_by, sort_dir


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
            old_cost = item.item_cost
            cost_history_added = False
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

            # Record manual cost change only if cost already existed
            if old_cost is not None and old_cost != item.item_cost:
                from qventory.models.item_cost_history import ItemCostHistory
                history = ItemCostHistory(
                    user_id=current_user.id,
                    item_id=item.id,
                    source="manual",
                    previous_cost=old_cost,
                    new_cost=item.item_cost,
                    delta=(item.item_cost - old_cost) if item.item_cost is not None else (-old_cost),
                    note="Inline edit"
                )
                db.session.add(history)
                cost_history_added = True
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
            response_data["cost_history_added"] = cost_history_added
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
            text(
                "SELECT COUNT(*) FROM items "
                "WHERE user_id = :user_id AND is_active = true AND COALESCE(inactive_by_user, FALSE) = FALSE"
            ),
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
                    text(
                        "SELECT COUNT(*) FROM items "
                        "WHERE user_id = :user_id AND is_active = true AND COALESCE(inactive_by_user, FALSE) = FALSE"
                    ),
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
                            text(
                                "SELECT COUNT(*) FROM items "
                                "WHERE user_id = :user_id AND is_active = true AND COALESCE(inactive_by_user, FALSE) = FALSE"
                            ),
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
        Item.inactive_by_user.is_(False),
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
    seed_help_articles()
    recommended_article = HelpArticle.query.filter_by(is_published=True)\
        .order_by(func.random())\
        .first()

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

    if (
        plan_max_items is not None
        and items_remaining is not None
        and items_remaining <= 0
    ):
        try:
            from qventory.models.notification import Notification
            from datetime import timedelta
            recent_cutoff = datetime.utcnow() - timedelta(hours=24)
            recent_email = Notification.query.filter(
                Notification.user_id == current_user.id,
                Notification.source == "plan_limit_email",
                Notification.created_at >= recent_cutoff
            ).first()
            if not recent_email:
                from qventory.helpers.email_sender import send_plan_limit_reached_email
                send_plan_limit_reached_email(
                    current_user.email,
                    current_user.username,
                    plan_max_items
                )
                Notification.create_notification(
                    user_id=current_user.id,
                    type='warning',
                    title='Plan Limit Reached',
                    message='You have reached your plan limit. Upgrade to add more active items.',
                    link_url='/upgrade',
                    link_text='Upgrade Plan',
                    source='plan_limit_email'
                )
        except Exception:
            pass

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
        today_listings_count=today_listings_count,
        recommended_article=recommended_article
    )


@main_bp.route("/upgrade")
@login_required
def upgrade():
    """Show upgrade page with plan comparison (non-functional placeholder)"""
    from qventory.models.subscription import PlanLimit
    from qventory.models.ai_token import AITokenConfig
    from qventory.models.system_setting import SystemSetting

    # Get all plan limits
    plans = PlanLimit.query.filter(
        ~PlanLimit.plan.in_(["early_adopter", "god", "enterprise"])
    ).order_by(
        db.case(
            (PlanLimit.plan == 'free', 1),
            (PlanLimit.plan == 'premium', 2),
            (PlanLimit.plan == 'plus', 3),
            (PlanLimit.plan == 'pro', 4),
            else_=99
        )
    ).all()

    # Get current user's plan info
    subscription = current_user.get_subscription()
    current_plan_limits = current_user.get_plan_limits()
    items_remaining = current_user.items_remaining()
    token_configs = {
        cfg.role: cfg
        for cfg in AITokenConfig.query.all()
    }
    trial_days = SystemSetting.get_int('stripe_trial_days', 10)

    stripe_status = request.args.get("stripe")
    if stripe_status == "success":
        flash("Stripe checkout completed. Your plan will update shortly.", "ok")
    elif stripe_status == "cancel":
        flash("Stripe checkout cancelled.", "info")

    return render_template(
        "upgrade.html",
        plans=plans,
        current_plan=current_plan_limits,
        current_user_plan=subscription.plan if subscription else None,
        items_remaining=items_remaining,
        token_configs=token_configs,
        trial_days=trial_days
    )


@main_bp.route("/pricing")
def pricing():
    """Public pricing page (clone of upgrade without auth)"""
    from qventory.models.subscription import PlanLimit
    from qventory.models.ai_token import AITokenConfig
    from qventory.models.system_setting import SystemSetting

    plans = PlanLimit.query.filter(
        ~PlanLimit.plan.in_(["early_adopter", "god", "enterprise"])
    ).order_by(
        db.case(
            (PlanLimit.plan == 'free', 1),
            (PlanLimit.plan == 'premium', 2),
            (PlanLimit.plan == 'plus', 3),
            (PlanLimit.plan == 'pro', 4),
            else_=99
        )
    ).all()

    token_configs = {cfg.role: cfg for cfg in AITokenConfig.query.all()}
    trial_days = SystemSetting.get_int('stripe_trial_days', 10)

    return render_template(
        "pricing.html",
        plans=plans,
        token_configs=token_configs,
        trial_days=trial_days
    )


# ---------------------- Inventory Views ----------------------

@main_bp.route("/inventory/active")
@login_required
def inventory_active():
    """Show only active items (is_active=True)"""
    s = get_or_create_settings(current_user)

    page, per_page, offset = _get_pagination_params()
    filters = _get_inventory_filter_params()
    sort_by, sort_dir = _get_inventory_sort_params()
    items, total_items = fetch_active_items(
        db.session,
        user_id=current_user.id,
        limit=per_page,
        offset=offset,
        sort_by=sort_by,
        sort_dir=sort_dir,
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
            sort_by=sort_by,
            sort_dir=sort_dir,
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
        sort_by=sort_by,
        sort_dir=sort_dir,
        items_remaining=items_remaining,
        plan_max_items=plan_max_items,
        show_upgrade_banner=show_upgrade_banner,
        upgrade_banner_dismiss_key=f"upgrade_banner_dismissed_{current_user.id}"
    )


@main_bp.route("/inventory/inactive")
@login_required
def inventory_inactive_by_user():
    """Show items hidden by the user (inactive_by_user=True)"""
    s = get_or_create_settings(current_user)

    page, per_page, offset = _get_pagination_params()
    filters = _get_inventory_filter_params()
    filters.pop("missing_data", None)
    sort_by, sort_dir = _get_inventory_sort_params()
    items, total_items = fetch_inactive_by_user_items(
        db.session,
        user_id=current_user.id,
        limit=per_page,
        offset=offset,
        sort_by=sort_by,
        sort_dir=sort_dir,
        **filters,
    )

    if total_items and offset >= total_items and page > 1:
        total_pages = max(1, math.ceil(total_items / per_page))
        page = total_pages
        offset = (page - 1) * per_page
        items, total_items = fetch_inactive_by_user_items(
            db.session,
            user_id=current_user.id,
            limit=per_page,
            offset=offset,
            sort_by=sort_by,
            sort_dir=sort_dir,
            **filters,
        )

    pagination = _build_pagination_metadata(total_items, page, per_page)

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

    return render_template(
        "inventory_list.html",
        items=items,
        settings=s,
        options=options,
        total_items=total_items,
        pagination=pagination,
        view_type="inactive_user",
        page_title="Inactive Items",
        sort_by=sort_by,
        sort_dir=sort_dir,
        items_remaining=None,
        plan_max_items=None,
        show_upgrade_banner=False,
        upgrade_banner_dismiss_key=f"upgrade_banner_dismissed_{current_user.id}"
    )


@main_bp.route("/inventory/sold")
@login_required
def inventory_sold():
    """Show items that have been sold (have sales records)"""
    s = get_or_create_settings(current_user)

    page, per_page, offset = _get_pagination_params()
    filters = _get_inventory_filter_params()
    sort_by, sort_dir = _get_inventory_sort_params()
    items, total_items = fetch_sold_items(
        db.session,
        user_id=current_user.id,
        limit=per_page,
        offset=offset,
        sort_by=sort_by,
        sort_dir=sort_dir,
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
            sort_by=sort_by,
            sort_dir=sort_dir,
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
        sort_by=sort_by,
        sort_dir=sort_dir,
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
    """Show fulfillment orders in a single table"""
    from ..models.sale import Sale

    # Pagination params for unified table
    try:
        page = int(request.args.get("page", 1))
    except (TypeError, ValueError):
        page = 1
    page = max(page, 1)

    try:
        per_page = int(request.args.get("per_page", 20))
    except (TypeError, ValueError):
        per_page = 20
    if per_page not in PAGE_SIZES:
        per_page = 20
    offset = (page - 1) * per_page

    orders, total_orders = fetch_fulfillment_orders(
        db.session,
        user_id=current_user.id,
        fulfillment_only=True,
        limit=per_page,
        offset=offset,
    )

    # Resolve titles and SKUs
    for order in orders:
        if getattr(order, "resolved_title", None):
            order.item_title = order.resolved_title
        if getattr(order, "resolved_sku", None):
            order.item_sku = order.resolved_sku

    shipped_count = Sale.query.filter(
        Sale.user_id == current_user.id,
        Sale.shipped_at.isnot(None),
        Sale.delivered_at.is_(None)
    ).count()

    delivered_count = Sale.query.filter(
        Sale.user_id == current_user.id,
        Sale.delivered_at.isnot(None)
    ).count()

    pagination = _build_independent_pagination(
        total_items=total_orders,
        page=page,
        per_page=per_page,
        page_param="page",
        per_page_param="per_page",
    )

    # Calculate total value across all fulfilled orders
    total_value = db.session.query(func.coalesce(func.sum(Sale.sold_price), 0)).filter(
        Sale.user_id == current_user.id,
        or_(Sale.shipped_at.isnot(None), Sale.delivered_at.isnot(None))
    ).scalar()

    return render_template(
        "fulfillment.html",
        fulfillment_orders=orders,
        shipped_count=shipped_count,
        delivered_count=delivered_count,
        total_orders=total_orders,
        total_value=total_value or 0,
        fulfillment_pagination=pagination,
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
                        'delivery_status': details.get('deliveryStatus'),
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
    from qventory.tasks import sync_ebay_fulfillment_tracking_user

    try:
        task = sync_ebay_fulfillment_tracking_user.delay(current_user.id)
        return jsonify({
            'success': True,
            'task_id': str(task.id)
        })

    except Exception as e:
        db.session.rollback()
        print(f"[FULFILLMENT_SYNC] Error: {str(e)}", file=sys.stderr)
        return jsonify({
            'success': False,
            'error': f'Sync failed: {str(e)}'
        }), 500


@main_bp.route("/fulfillment/sync-ebay-orders/status/<task_id>", methods=["GET"])
@login_required
def sync_ebay_orders_status(task_id):
    """Check status for fulfillment sync task."""
    from qventory.celery_app import celery

    result = celery.AsyncResult(task_id)
    payload = {
        'state': result.state
    }

    if result.state == 'SUCCESS':
        data = result.result or {}
        message = data.get('message')
        if not message:
            message = f"Synced {data.get('orders_created', 0)} new and updated {data.get('orders_updated', 0)} existing orders"
        payload.update({
            'success': True,
            'message': message,
            'orders_synced': data.get('orders_synced', 0),
            'orders_created': data.get('orders_created', 0),
            'orders_updated': data.get('orders_updated', 0)
        })
    elif result.state in ['FAILURE', 'REVOKED']:
        payload.update({
            'success': False,
            'error': str(result.result) if result.result else 'Sync failed'
        })
    else:
        payload.update({
            'success': None
        })

    return jsonify(payload)


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
        current_item_count = Item.query.filter(
            Item.user_id == current_user.id,
            Item.is_active.is_(True),
            Item.inactive_by_user.is_(False)
        ).count()

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
            Item.ebay_listing_id.isnot(None),
            Item.is_active.is_(True),
            Item.inactive_by_user.is_(False)
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
                    listing_id = str(offer_data['ebay_listing_id'])
                    with db.session.no_autoflush:
                        existing = Item.query.filter(
                            Item.user_id == current_user.id,
                            Item.ebay_listing_id == listing_id,
                            Item.id != item.id
                        ).first()
                    if existing:
                        print(
                            f"[SYNC_INVENTORY] Skipping listing_id {listing_id} for item {item.id}: "
                            f"already on item {existing.id}",
                            file=sys.stderr
                        )
                    else:
                        item.ebay_listing_id = listing_id
                if not item.ebay_sku and offer_data.get('ebay_sku'):
                    item.ebay_sku = offer_data['ebay_sku']

                # Update listing status (reactivate if present and active)
                listing_status = str(offer_data.get('listing_status', 'ACTIVE')).upper()
                active_statuses = {'PUBLISHED', 'ACTIVE', 'IN_PROGRESS', 'SCHEDULED', 'ON_HOLD', 'LIVE'}
                if listing_status in active_statuses or not listing_status:
                    if not item.is_active:
                        item.is_active = True
            else:
                if can_mark_inactive:
                    # SOFT DELETE: Item no longer exists on eBay (sold/removed) - mark as inactive
                    print(f"[SYNC_INVENTORY] Item no longer on eBay, marking inactive: {item.title} (ID: {item.id}, eBay: {item.ebay_listing_id})", file=sys.stderr)
                    if item.is_active:
                        item.is_active = False
                        try:
                            from qventory.helpers.link_bio import remove_featured_items_for_user
                            remove_featured_items_for_user(current_user.id, [item.id])
                        except Exception:
                            pass
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

def _ebay_analytics_base():
    if EBAY_ENV == "sandbox":
        return "https://api.sandbox.ebay.com/developer/analytics/v1_beta"
    return "https://api.ebay.com/developer/analytics/v1_beta"

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


def _normalize_rate_limits(payload):
    if not payload:
        return []
    if isinstance(payload, dict) and isinstance(payload.get("rateLimits"), list):
        return payload["rateLimits"]
    return []


def _flatten_rate_limits(rate_limits):
    rows = []
    for rl in rate_limits:
        api_context = rl.get("apiContext")
        api_name = rl.get("apiName")
        api_version = rl.get("apiVersion")
        resources = rl.get("resources") or []
        for resource in resources:
            resource_name = resource.get("name")
            rates = resource.get("rates") or []
            for rate in rates:
                rows.append({
                    "api_context": api_context,
                    "api_name": api_name,
                    "api_version": api_version,
                    "resource_name": resource_name,
                    "count": rate.get("count"),
                    "limit": rate.get("limit"),
                    "remaining": rate.get("remaining"),
                    "reset": rate.get("reset"),
                    "time_window": rate.get("timeWindow"),
                })
    return rows


def _compute_usage_stats(limit_entry):
    limit = limit_entry.get("limit")
    remaining = limit_entry.get("remaining")
    count = limit_entry.get("count")
    used = count if isinstance(count, int) else None
    if used is None and isinstance(limit, int) and isinstance(remaining, int):
        used = max(limit - remaining, 0)
    pct = round((used / limit) * 100, 1) if isinstance(limit, int) and limit > 0 and isinstance(used, int) else None
    return used, pct


@main_bp.route("/admin/ebay-api-usage")
@require_admin
def admin_ebay_api_usage():
    """Admin view: eBay API usage (global app-level only)."""
    app_limits = []
    app_rows = []
    app_error = None
    analytics_base = _ebay_analytics_base()
    view = (request.args.get("view") or "import").lower()
    api_filter = (request.args.get("api") or "all").lower()
    import_filters = {
        "TradingAPI:GetSellerEvents",
        "TradingAPI:GetMyeBaySelling",
        "sell.inventory:sell.inventory",
        "sell.fulfillment:sell.fulfillment",
        "payoutapi.sell.finances:payoutapi.sell.finances"
    }

    try:
        app_token = _get_ebay_app_token()
        headers = {"Authorization": f"Bearer {app_token}"}
        r = requests.get(f"{analytics_base}/rate_limit/", headers=headers, timeout=15)
        if r.status_code == 204:
            app_limits = []
        elif r.status_code != 200:
            app_error = f"HTTP {r.status_code}: {r.text[:200]}"
        else:
            app_limits = _normalize_rate_limits(r.json())
            app_rows = _flatten_rate_limits(app_limits)
    except Exception as exc:
        app_error = str(exc)

    if view == "import":
        def _key(row):
            return f"{row.get('api_context')}:{row.get('api_name')}"
        app_rows = [row for row in app_rows if _key(row) in import_filters]

    if api_filter != "all":
        def _api_match(row):
            ctx = (row.get("api_context") or "").lower()
            name = (row.get("api_name") or "").lower()
            if api_filter == "trading":
                return ctx == "tradingapi" or name == "tradingapi"
            if api_filter == "finances":
                return "finances" in name or "payout" in name
            if api_filter == "inventory":
                return "inventory" in name
            if api_filter == "fulfillment":
                return "fulfillment" in name
            if api_filter == "sell":
                return ctx == "sell" or name.startswith("sell.")
            if api_filter == "buy":
                return ctx == "buy" or name.startswith("buy.")
            return True
        app_rows = [row for row in app_rows if _api_match(row)]

    return render_template(
        "admin_ebay_api_usage.html",
        app_limits=app_limits,
        app_rows=app_rows,
        app_error=app_error,
        compute_usage=_compute_usage_stats,
        view=view,
        api_filter=api_filter
    )


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


@main_bp.route("/api/upload-store-image", methods=["POST"])
@login_required
def api_upload_store_image():
    if not cloudinary_enabled:
        return jsonify({"ok": False, "error": "Cloudinary not configured"}), 503

    f = request.files.get("file")
    if not f:
        return jsonify({"ok": False, "error": "Missing file"}), 400

    ct = (f.mimetype or "").lower()
    if not ct.startswith("image/"):
        return jsonify({"ok": False, "error": "Only image files are allowed"}), 400

    f.seek(0, io.SEEK_END)
    size = f.tell()
    f.seek(0)
    if size > 1 * 1024 * 1024:
        return jsonify({"ok": False, "error": "Image too large (max 1MB)"}), 400

    try:
        up = cloudinary.uploader.upload(
            f,
            folder=CLOUDINARY_STORE_FOLDER,
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
    if it.synced_from_ebay or it.ebay_listing_id:
        flash("eBay-synced items can’t be edited here. Use Update & Relist instead.", "error")
        return redirect(url_for("main.inventory_active"))
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


@main_bp.route("/item/<int:item_id>")
@login_required
def item_detail(item_id):
    it = Item.query.filter_by(id=item_id, user_id=current_user.id).first_or_404()

    events = []
    if it.created_at:
        origin = "Imported from eBay" if it.synced_from_ebay else "Created in Qventory"
        events.append({
            "timestamp": it.created_at,
            "title": "Item added",
            "detail": origin
        })

    if it.supplier:
        events.append({
            "timestamp": it.updated_at or it.created_at,
            "title": "Supplier assigned",
            "detail": it.supplier
        })

    if it.location_code:
        events.append({
            "timestamp": it.updated_at or it.created_at,
            "title": "Location assigned",
            "detail": it.location_code
        })

    cost_events = []
    history_entries = ItemCostHistory.query.filter_by(
        user_id=current_user.id,
        item_id=it.id
    ).order_by(ItemCostHistory.created_at.asc()).all()
    for entry in history_entries:
        cost_events.append({
            "timestamp": entry.created_at,
            "title": "Cost updated",
            "detail": f"{entry.source.capitalize()} update: {entry.previous_cost} → {entry.new_cost}"
        })

    expense_entries = Expense.query.filter_by(
        user_id=current_user.id,
        item_id=it.id,
        item_cost_applied=True
    ).order_by(Expense.item_cost_applied_at.asc()).all()
    for exp in expense_entries:
        cost_events.append({
            "timestamp": exp.item_cost_applied_at or exp.updated_at or exp.created_at,
            "title": "Expense applied to cost",
            "detail": f"{exp.description} (${exp.item_cost_applied_amount or exp.amount})"
        })

    receipt_entries = ReceiptItem.query.filter_by(
        inventory_item_id=it.id
    ).order_by(ReceiptItem.associated_at.asc()).all()
    for ri in receipt_entries:
        cost_events.append({
            "timestamp": ri.associated_at or ri.updated_at or ri.created_at,
            "title": "Receipt item linked",
            "detail": f"{ri.final_description} (${ri.final_total_price or ri.final_unit_price or '—'})"
        })

    if not cost_events and it.item_cost is not None:
        cost_events.append({
            "timestamp": it.updated_at or it.created_at,
            "title": "Cost set",
            "detail": f"${it.item_cost:.2f}"
        })

    events.extend(cost_events)

    relist_events = []
    chain_items = [it]
    seen_item_ids = {it.id}
    current = it
    for _ in range(10):
        if not current.previous_item_id:
            break
        prev_item = Item.query.filter_by(
            user_id=current_user.id,
            id=current.previous_item_id
        ).first()
        if not prev_item or prev_item.id in seen_item_ids:
            break
        chain_items.append(prev_item)
        seen_item_ids.add(prev_item.id)
        current = prev_item

    relist_filters = [AutoRelistHistory.user_id == current_user.id]
    relist_match = []
    chain_skus = [ci.sku for ci in chain_items if ci.sku]
    chain_listing_ids = [ci.ebay_listing_id for ci in chain_items if ci.ebay_listing_id]
    if seen_item_ids:
        relist_match.append(AutoRelistHistory.item_id.in_(list(seen_item_ids)))
    if chain_skus:
        relist_match.append(AutoRelistHistory.sku.in_(chain_skus))
    if chain_listing_ids:
        relist_match.append(AutoRelistHistory.old_listing_id.in_(chain_listing_ids))
        relist_match.append(AutoRelistHistory.new_listing_id.in_(chain_listing_ids))

    if relist_match:
        relist_filters.append(or_(*relist_match))
        relist_history = AutoRelistHistory.query.filter(
            *relist_filters
        ).order_by(AutoRelistHistory.started_at.asc()).all()
        for rh in relist_history:
            detail = f"Status: {rh.status}"
            if rh.old_price is not None or rh.new_price is not None:
                old_price = f"{rh.old_price:.2f}" if rh.old_price is not None else "—"
                new_price = f"{rh.new_price:.2f}" if rh.new_price is not None else "—"
                detail += f" • Price: {old_price} → {new_price}"
            if rh.old_title or rh.new_title:
                old_title = rh.old_title or "—"
                new_title = rh.new_title or "—"
                detail += f" • Title: {old_title} → {new_title}"
            relist_events.append({
                "timestamp": rh.started_at,
                "title": f"Relisted ({rh.mode or 'manual'})",
                "detail": detail
            })
    events.extend(relist_events)

    sales = Sale.query.filter_by(
        user_id=current_user.id,
        item_id=it.id
    ).order_by(Sale.sold_at.asc()).all()
    for sale in sales:
        if sale.sold_at:
            events.append({
                "timestamp": sale.sold_at,
                "title": "Sold",
                "detail": f"{sale.marketplace or 'Marketplace'} • ${sale.sold_price or 0:.2f}"
            })
        if sale.shipped_at:
            events.append({
                "timestamp": sale.shipped_at,
                "title": "Shipped",
                "detail": sale.marketplace_order_id or "Order shipped"
            })
        if sale.delivered_at:
            events.append({
                "timestamp": sale.delivered_at,
                "title": "Delivered",
                "detail": sale.marketplace_order_id or "Order delivered"
            })

    events = [e for e in events if e.get("timestamp")]
    events.sort(key=lambda e: e["timestamp"])

    return render_template(
        "item_detail.html",
        item=it,
        events=events
    )


@main_bp.route("/item/<int:item_id>/delete", methods=["POST"])
@login_required
def delete_item(item_id):
    it = Item.query.filter_by(id=item_id, user_id=current_user.id).first_or_404()
    if it.synced_from_ebay or it.ebay_listing_id:
        flash("eBay-synced items can’t be deleted from Qventory.", "error")
        return redirect(request.referrer or url_for("main.inventory_active"))

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

    # If there's a linked item, update its cost too and record history if needed
    cost_history_added = False
    if sale.item_id:
        item = Item.query.filter_by(id=sale.item_id, user_id=current_user.id).first()
        if item:
            old_cost = item.item_cost
            item.item_cost = item_cost
            if old_cost is not None and old_cost != item.item_cost:
                from qventory.models.item_cost_history import ItemCostHistory
                history = ItemCostHistory(
                    user_id=current_user.id,
                    item_id=item.id,
                    source="manual",
                    previous_cost=old_cost,
                    new_cost=item.item_cost,
                    delta=(item.item_cost - old_cost) if item.item_cost is not None else (-old_cost),
                    note="Sold view edit"
                )
                db.session.add(history)
                cost_history_added = True

    # Recalculate profit with new cost
    sale.calculate_profit()

    db.session.commit()

    if request.is_json:
        return jsonify({
            "ok": True,
            "sale_id": sale.id,
            "item_cost": sale.item_cost,
            "gross_profit": sale.gross_profit,
            "net_profit": sale.net_profit,
            "cost_history_added": cost_history_added
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
        blocked_items = [item for item in items_to_delete if item.synced_from_ebay or item.ebay_listing_id]
        if blocked_items:
            return jsonify({
                "ok": False,
                "error": "eBay-synced items cannot be deleted from Qventory. Deselect those items and try again."
            }), 400

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


@main_bp.route("/items/bulk_deactivate_by_user", methods=["POST"])
@login_required
def bulk_deactivate_by_user():
    """
    Bulk hide items from active inventory (inactive_by_user=True)
    Expects JSON: {"item_ids": [1, 2, 3, ...]}
    """
    try:
        data = request.get_json()
        if not data or 'item_ids' not in data:
            return jsonify({"ok": False, "error": "Missing item_ids"}), 400

        item_ids = data['item_ids']
        if not isinstance(item_ids, list):
            return jsonify({"ok": False, "error": "item_ids must be an array"}), 400

        try:
            item_ids = [int(x) for x in item_ids]
        except (ValueError, TypeError):
            return jsonify({"ok": False, "error": "Invalid item ID format"}), 400

        if len(item_ids) == 0:
            return jsonify({"ok": False, "error": "No items selected"}), 400

        items = Item.query.filter(
            Item.id.in_(item_ids),
            Item.user_id == current_user.id,
            Item.is_active.is_(True)
        ).all()

        if not items:
            return jsonify({"ok": False, "error": "No items found"}), 404

        updated_count = 0
        for item in items:
            if not item.inactive_by_user:
                item.inactive_by_user = True
                item.updated_at = datetime.utcnow()
                updated_count += 1

        db.session.commit()

        return jsonify({
            "ok": True,
            "updated_count": updated_count,
            "message": f"Hidden {updated_count} item(s) from active inventory"
        })

    except Exception as e:
        db.session.rollback()
        print(f"[BULK_DEACTIVATE_BY_USER] Error: {str(e)}", file=sys.stderr)
        return jsonify({"ok": False, "error": str(e)}), 500


@main_bp.route("/items/bulk_reactivate_by_user", methods=["POST"])
@login_required
def bulk_reactivate_by_user():
    """
    Bulk show items in active inventory (inactive_by_user=False)
    Expects JSON: {"item_ids": [1, 2, 3, ...]}
    """
    try:
        data = request.get_json()
        if not data or 'item_ids' not in data:
            return jsonify({"ok": False, "error": "Missing item_ids"}), 400

        item_ids = data['item_ids']
        if not isinstance(item_ids, list):
            return jsonify({"ok": False, "error": "item_ids must be an array"}), 400

        try:
            item_ids = [int(x) for x in item_ids]
        except (ValueError, TypeError):
            return jsonify({"ok": False, "error": "Invalid item ID format"}), 400

        if len(item_ids) == 0:
            return jsonify({"ok": False, "error": "No items selected"}), 400

        items = Item.query.filter(
            Item.id.in_(item_ids),
            Item.user_id == current_user.id,
            Item.is_active.is_(True),
            Item.inactive_by_user.is_(True)
        ).all()

        if not items:
            return jsonify({"ok": False, "error": "No items found"}), 404

        updated_count = 0
        for item in items:
            item.inactive_by_user = False
            item.updated_at = datetime.utcnow()
            updated_count += 1

        db.session.commit()

        return jsonify({
            "ok": True,
            "updated_count": updated_count,
            "message": f"Reactivated {updated_count} item(s) into active inventory"
        })

    except Exception as e:
        db.session.rollback()
        print(f"[BULK_REACTIVATE_BY_USER] Error: {str(e)}", file=sys.stderr)
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


@main_bp.route("/items/bulk_update_fields", methods=["POST"])
@login_required
def bulk_update_fields():
    """
    Bulk update supplier, cost, and/or location for multiple items.
    Expects JSON: {
        "item_ids": [1, 2, 3],
        "apply_supplier": true/false,
        "supplier": "value or empty",
        "apply_cost": true/false,
        "item_cost": "value or empty",
        "apply_location": true/false,
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

        try:
            item_ids = [int(x) for x in data['item_ids']]
        except (ValueError, TypeError):
            return jsonify({"ok": False, "error": "Invalid item ID format"}), 400

        if len(item_ids) == 0:
            return jsonify({"ok": False, "error": "No items selected"}), 400

        apply_supplier = bool(data.get('apply_supplier'))
        apply_cost = bool(data.get('apply_cost'))
        apply_location = bool(data.get('apply_location'))

        if not any([apply_supplier, apply_cost, apply_location]):
            return jsonify({"ok": False, "error": "No fields selected for update"}), 400

        # Parse supplier
        supplier_value = None
        if apply_supplier:
            supplier_raw = (data.get('supplier') or '').strip()
            supplier_value = supplier_raw if supplier_raw else None

        # Parse cost
        item_cost_value = None
        if apply_cost:
            cost_raw = data.get('item_cost')
            if cost_raw is not None and str(cost_raw).strip() != '':
                try:
                    item_cost_value = float(cost_raw)
                except (ValueError, TypeError):
                    return jsonify({"ok": False, "error": "Invalid cost value"}), 400
                if item_cost_value < 0:
                    return jsonify({"ok": False, "error": "Cost cannot be negative"}), 400
            else:
                item_cost_value = None

        # Parse location
        A = data.get('A') if apply_location else None
        B = data.get('B') if apply_location else None
        S = data.get('S') if apply_location else None
        C = data.get('C') if apply_location else None
        sync_to_ebay = bool(data.get('sync_to_ebay')) if apply_location else False

        from qventory.helpers import compose_location_code
        location_code = compose_location_code(A, B, S, C) if apply_location else None

        items = Item.query.filter(
            Item.id.in_(item_ids),
            Item.user_id == current_user.id
        ).all()

        if len(items) == 0:
            return jsonify({"ok": False, "error": "No items found"}), 404

        updated_count = 0
        synced_count = 0

        for item in items:
            if apply_supplier:
                item.supplier = supplier_value
            if apply_cost:
                item.item_cost = item_cost_value
            if apply_location:
                item.A = A
                item.B = B
                item.S = S
                item.C = C
                item.location_code = location_code

                if sync_to_ebay and item.ebay_listing_id and location_code:
                    from qventory.helpers.ebay_inventory import sync_location_to_ebay_sku
                    success = sync_location_to_ebay_sku(current_user.id, item.ebay_listing_id, location_code)
                    if success:
                        synced_count += 1

            updated_count += 1

        db.session.commit()

        message = f"Updated {updated_count} item(s)"
        if apply_location and sync_to_ebay and synced_count > 0:
            message += f" and synced {synced_count} to eBay"

        return jsonify({
            "ok": True,
            "updated_count": updated_count,
            "synced_count": synced_count,
            "message": message
        })

    except Exception as e:
        print(f"[BULK_UPDATE_FIELDS] Error: {str(e)}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        db.session.rollback()
        return jsonify({"ok": False, "error": str(e)}), 500


@main_bp.route("/items/relist", methods=["POST"])
@login_required
def relist_item_from_inventory():
    try:
        data = request.get_json() or {}
        item_id = data.get("item_id")
        if not item_id:
            return jsonify({"ok": False, "error": "Missing item_id"}), 400

        try:
            item_id = int(item_id)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "Invalid item_id"}), 400

        item = Item.query.filter_by(id=item_id, user_id=current_user.id).first()
        if not item:
            return jsonify({"ok": False, "error": "Item not found"}), 404

        if not (item.synced_from_ebay or item.ebay_listing_id):
            return jsonify({"ok": False, "error": "Item is not linked to eBay"}), 400

        listing_id = item.ebay_listing_id
        if not listing_id:
            return jsonify({"ok": False, "error": "Missing eBay listing ID"}), 400

        changes = {}
        title = (data.get("title") or "").strip()
        if title:
            changes["title"] = title

        price_raw = (data.get("price") or "").strip()
        if price_raw:
            try:
                changes["price"] = float(price_raw)
            except ValueError:
                return jsonify({"ok": False, "error": "Invalid price"}), 400

        from qventory.tasks import relist_item_sell_similar

        task = relist_item_sell_similar.apply_async(
            args=[current_user.id, item.id, title or None, changes.get("price")],
            priority=1
        )

        return jsonify({
            "ok": True,
            "task_id": task.id,
            "message": "Relist queued"
        })

    except Exception as e:
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
        theme_pref = request.form.get("theme_preference")
        if theme_pref:
            theme_pref = theme_pref.strip().lower()
            if theme_pref in {"dark", "light"}:
                s.theme_preference = theme_pref
                db.session.commit()
                return redirect(url_for("main.settings"))
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
    from qventory.models.subscription import PlanLimit
    subscription = _refresh_subscription_from_stripe(current_user.get_subscription())
    plan_limits = PlanLimit.query.filter_by(plan=subscription.plan).first() if subscription else None

    return render_template("settings.html",
                         settings=s,
                         ebay_connected=ebay_connected,
                         ebay_username=ebay_username,
                         subscription=subscription,
                         plan_limits=plan_limits)


@main_bp.route("/settings/suppliers", methods=["GET"])
@login_required
def settings_suppliers():
    s = get_or_create_settings(current_user)
    return render_template("settings_suppliers.html", settings=s)


@main_bp.route("/api/suppliers", methods=["GET"])
@login_required
def api_suppliers():
    from sqlalchemy import func

    rows = db.session.query(
        Item.supplier,
        func.count(Item.id)
    ).filter(
        Item.user_id == current_user.id
    ).group_by(Item.supplier).all()

    suppliers = []
    unassigned_count = 0

    for name, count in rows:
        supplier_name = (name or "").strip()
        if not supplier_name:
            unassigned_count += int(count or 0)
            continue
        suppliers.append({
            "name": supplier_name,
            "count": int(count or 0)
        })

    suppliers.sort(key=lambda s: (-s["count"], s["name"].lower()))

    return jsonify({
        "ok": True,
        "suppliers": suppliers,
        "unassigned": unassigned_count
    })


@main_bp.route("/api/suppliers/rename", methods=["POST"])
@login_required
def api_suppliers_rename():
    data = request.get_json(silent=True) or {}
    old_name = (data.get("old_name") or "").strip()
    new_name = (data.get("new_name") or "").strip()

    if not old_name:
        return jsonify({"ok": False, "error": "Missing old supplier name"}), 400
    if not new_name:
        return jsonify({"ok": False, "error": "New supplier name required"}), 400
    if old_name == new_name:
        return jsonify({"ok": True, "updated": 0})

    updated = Item.query.filter(
        Item.user_id == current_user.id,
        Item.supplier == old_name
    ).update({Item.supplier: new_name})

    db.session.commit()
    return jsonify({"ok": True, "updated": updated})


@main_bp.route("/api/suppliers/delete", methods=["POST"])
@login_required
def api_suppliers_delete():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    target = (data.get("target") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "Missing supplier name"}), 400

    if target and target.lower() != "unassigned":
        updated = Item.query.filter(
            Item.user_id == current_user.id,
            Item.supplier == name
        ).update({Item.supplier: target})
    else:
        updated = Item.query.filter(
            Item.user_id == current_user.id,
            Item.supplier == name
        ).update({Item.supplier: None})

    db.session.commit()
    return jsonify({"ok": True, "updated": updated})


def _build_link_bio_context(user, settings):
    import json
    from qventory.models.marketplace_credential import MarketplaceCredential

    ebay_cred = MarketplaceCredential.query.filter_by(
        user_id=user.id,
        marketplace='ebay',
        is_active=True
    ).first()
    ebay_username = ebay_cred.ebay_user_id if ebay_cred else None
    ebay_store_url = f"https://www.ebay.com/str/{ebay_username}" if ebay_username else None

    link_bio_links = []
    if settings.link_bio_links_json:
        try:
            link_bio_links = json.loads(settings.link_bio_links_json)
        except Exception:
            link_bio_links = []

    featured_ids = []
    if settings.link_bio_featured_json:
        try:
            featured_ids = json.loads(settings.link_bio_featured_json) or []
        except Exception:
            featured_ids = []

    items_active = (
        Item.query.filter(
            Item.user_id == user.id,
            Item.is_active.is_(True),
            Item.inactive_by_user.is_(False)
        )
        .order_by(Item.title.asc())
        .all()
    )
    if featured_ids:
        active_ids = {item.id for item in items_active}
        filtered_ids = [item_id for item_id in featured_ids if item_id in active_ids]
        if filtered_ids != featured_ids:
            settings.link_bio_featured_json = json.dumps(filtered_ids)
            db.session.commit()
            featured_ids = filtered_ids
    featured_titles = {item.id: item.title for item in items_active}

    return {
        "ebay_store_url": ebay_store_url,
        "link_bio_links": link_bio_links,
        "link_bio_featured_ids": featured_ids,
        "items_active": items_active,
        "link_bio_featured_titles": featured_titles,
    }


def _save_link_bio_settings(settings, form, user_id):
    import json
    slug_raw = (form.get("link_bio_slug") or "").strip().lower()
    if slug_raw:
        if not re.match(r"^[a-z0-9][a-z0-9-]{2,59}$", slug_raw):
            return "Custom link must be 3-60 chars, lowercase letters, numbers, or dashes."

        slug_exists = Setting.query.filter(
            Setting.link_bio_slug == slug_raw,
            Setting.user_id != user_id
        ).first()
        user_conflict = User.query.filter(
            db.func.lower(User.username) == slug_raw,
            User.id != user_id
        ).first()
        if slug_exists or user_conflict:
            return "That custom link is already taken."

        settings.link_bio_slug = slug_raw
    else:
        settings.link_bio_slug = None

    settings.link_bio_bio = (form.get("link_bio_bio") or "").strip()
    settings.link_bio_image_url = (form.get("link_bio_image_url") or "").strip() or None

    links = []
    label_1 = (form.get("link_bio_label_1") or "").strip() or "Poshmark"
    url_1 = (form.get("link_bio_url_1") or "").strip()
    if url_1:
        links.append({"label": label_1, "url": url_1})

    label_2 = (form.get("link_bio_label_2") or "").strip() or "Etsy"
    url_2 = (form.get("link_bio_url_2") or "").strip()
    if url_2:
        links.append({"label": label_2, "url": url_2})

    extra_labels = form.getlist("link_bio_extra_label")
    extra_urls = form.getlist("link_bio_extra_url")
    for label, url in zip(extra_labels, extra_urls):
        label = (label or "").strip()
        url = (url or "").strip()
        if not url:
            continue
        links.append({"label": label or "Shop", "url": url})

    settings.link_bio_links_json = json.dumps(links)

    featured_ids = []
    for key in (
        "link_bio_featured_1",
        "link_bio_featured_2",
        "link_bio_featured_3",
        "link_bio_featured_4",
        "link_bio_featured_5",
    ):
        raw = (form.get(key) or "").strip()
        if not raw:
            continue
        try:
            featured_ids.append(int(raw))
        except ValueError:
            continue
    if featured_ids:
        featured_ids = list(dict.fromkeys(featured_ids))[:5]
        active_ids = {
            item.id
            for item in Item.query.filter(
                Item.user_id == user_id,
                Item.is_active.is_(True),
                Item.id.in_(featured_ids)
            ).all()
        }
        featured_ids = [item_id for item_id in featured_ids if item_id in active_ids]
    settings.link_bio_featured_json = json.dumps(featured_ids)

    return None


@main_bp.route("/settings/link-bio", methods=["GET", "POST"])
@login_required
def settings_link_bio():
    s = get_or_create_settings(current_user)
    if request.method == "POST":
        error = _save_link_bio_settings(s, request.form, current_user.id)
        if error:
            flash(error, "error")
            return redirect(url_for("main.settings_link_bio"))
        db.session.commit()
        flash("Link in bio saved.", "ok")
        return redirect(url_for("main.settings_link_bio"))

    ctx = _build_link_bio_context(current_user, s)
    return render_template(
        "settings_link_bio.html",
        settings=s,
        cloudinary_enabled=cloudinary_enabled,
        **ctx
    )


@main_bp.route("/settings/labels", methods=["GET", "POST"])
@login_required
def settings_labels():
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
        flash("Location settings saved.", "ok")
        return redirect(url_for("main.settings_labels"))

    return render_template("settings_labels.html", settings=s)


@main_bp.route("/settings/theme", methods=["GET", "POST"])
@login_required
def settings_theme():
    s = get_or_create_settings(current_user)
    if request.method == "POST":
        theme_pref = request.form.get("theme_preference")
        if theme_pref:
            theme_pref = theme_pref.strip().lower()
            if theme_pref in {"dark", "light"}:
                s.theme_preference = theme_pref
                db.session.commit()
        return redirect(url_for("main.settings_theme"))

    return render_template("settings_theme.html", settings=s)


@main_bp.route("/settings/subscription", methods=["GET"])
@login_required
def settings_subscription():
    from qventory.models.subscription import PlanLimit
    subscription = _refresh_subscription_from_stripe(current_user.get_subscription())
    plan_limits = PlanLimit.query.filter_by(plan=subscription.plan).first() if subscription else None
    return render_template(
        "settings_subscription.html",
        subscription=subscription,
        plan_limits=plan_limits
    )


@main_bp.route("/settings/support", methods=["GET"])
@login_required
def settings_support():
    return render_template("settings_support.html")


# ---------------------- Support Tickets ----------------------

@main_bp.route("/support", methods=["GET", "POST"])
@login_required
def support_inbox():
    can_create_ticket = _support_access_allowed(current_user)
    if not can_create_ticket and not _support_broadcast_exists(current_user.id):
        flash("Support is available for paid plans only.", "error")
        return redirect(url_for("main.dashboard"))

    open_count = _support_open_count(current_user.id)
    max_open = 3

    if request.method == "POST":
        if not can_create_ticket:
            flash("Support tickets are available for paid plans only.", "error")
            return redirect(url_for("main.support_inbox"))
        if open_count >= max_open:
            flash("You already have 3 open tickets. Close one to create a new ticket.", "error")
            return redirect(url_for("main.support_inbox"))

        subject = (request.form.get("subject") or "").strip()
        body = (request.form.get("body") or "").strip()

        if not subject or not body:
            flash("Subject and message are required.", "error")
            return redirect(url_for("main.support_inbox"))

        ticket = SupportTicket(
            ticket_code=_support_ticket_code(),
            user_id=current_user.id,
            subject=subject[:200],
            status="open",
        )
        db.session.add(ticket)
        db.session.flush()

        message = SupportMessage(
            ticket_id=ticket.id,
            sender_role="user",
            body=body,
            is_read_by_user=True,
            is_read_by_admin=False,
        )
        db.session.add(message)
        db.session.flush()

        files = request.files.getlist("attachments")
        uploads, error = _upload_support_attachments(
            files, user_id=current_user.id, ticket_code=ticket.ticket_code
        )
        if error:
            db.session.rollback()
            flash(error, "error")
            return redirect(url_for("main.support_inbox"))

        for item in uploads:
            db.session.add(SupportAttachment(
                message_id=message.id,
                image_url=item["url"],
                public_id=item.get("public_id"),
                filename=item.get("filename"),
                bytes=item.get("bytes"),
            ))

        db.session.commit()
        flash("Support ticket created.", "ok")
        return redirect(url_for("main.support_detail", ticket_code=ticket.ticket_code))

    tickets = SupportTicket.query.filter_by(user_id=current_user.id)\
        .order_by(SupportTicket.updated_at.desc()).all()

    unread_counts = dict(
        db.session.query(SupportMessage.ticket_id, func.count(SupportMessage.id))
        .join(SupportTicket, SupportTicket.id == SupportMessage.ticket_id)
        .filter(
            SupportTicket.user_id == current_user.id,
            SupportMessage.sender_role == "admin",
            SupportMessage.is_read_by_user.is_(False),
        )
        .group_by(SupportMessage.ticket_id)
        .all()
    )

    return render_template(
        "support/index.html",
        tickets=tickets,
        unread_counts=unread_counts,
        open_count=open_count,
        max_open=max_open,
        can_create_ticket=can_create_ticket,
        cloudinary_enabled=cloudinary_enabled,
    )


@main_bp.route("/support/<ticket_code>")
@login_required
def support_detail(ticket_code):
    ticket = SupportTicket.query.filter_by(
        ticket_code=ticket_code,
        user_id=current_user.id
    ).first_or_404()
    if not _support_access_allowed(current_user) and ticket.kind != "broadcast":
        flash("Support is available for paid plans only.", "error")
        return redirect(url_for("main.dashboard"))

    SupportMessage.query.filter_by(
        ticket_id=ticket.id,
        sender_role="admin",
        is_read_by_user=False
    ).update({"is_read_by_user": True})
    db.session.commit()

    messages = ticket.messages.order_by(SupportMessage.created_at.asc()).all()

    return render_template(
        "support/detail.html",
        ticket=ticket,
        messages=messages,
        cloudinary_enabled=cloudinary_enabled,
    )


@main_bp.route("/support/<ticket_code>/message", methods=["POST"])
@login_required
def support_send_message(ticket_code):
    ticket = SupportTicket.query.filter_by(
        ticket_code=ticket_code,
        user_id=current_user.id
    ).first_or_404()
    if not _support_access_allowed(current_user) and ticket.kind != "broadcast":
        flash("Support is available for paid plans only.", "error")
        return redirect(url_for("main.dashboard"))

    if ticket.status != "open":
        flash("This ticket is closed. You can’t reply.", "error")
        return redirect(url_for("main.support_detail", ticket_code=ticket_code))
    if ticket.requires_ack or ticket.kind == "broadcast":
        flash("This ticket does not accept replies.", "error")
        return redirect(url_for("main.support_detail", ticket_code=ticket_code))

    body = (request.form.get("body") or "").strip()
    if not body:
        flash("Message cannot be empty.", "error")
        return redirect(url_for("main.support_detail", ticket_code=ticket_code))

    message = SupportMessage(
        ticket_id=ticket.id,
        sender_role="user",
        body=body,
        is_read_by_user=True,
        is_read_by_admin=False,
    )
    db.session.add(message)
    db.session.flush()

    files = request.files.getlist("attachments")
    uploads, error = _upload_support_attachments(
        files, user_id=current_user.id, ticket_code=ticket.ticket_code
    )
    if error:
        db.session.rollback()
        flash(error, "error")
        return redirect(url_for("main.support_detail", ticket_code=ticket_code))

    for item in uploads:
        db.session.add(SupportAttachment(
            message_id=message.id,
            image_url=item["url"],
            public_id=item.get("public_id"),
            filename=item.get("filename"),
            bytes=item.get("bytes"),
        ))

    ticket.updated_at = datetime.utcnow()
    db.session.commit()
    return redirect(url_for("main.support_detail", ticket_code=ticket_code))


@main_bp.route("/support/<ticket_code>/ack", methods=["POST"])
@login_required
def support_acknowledge(ticket_code):
    ticket = SupportTicket.query.filter_by(
        ticket_code=ticket_code,
        user_id=current_user.id
    ).first_or_404()
    if ticket.kind != "broadcast" or not ticket.requires_ack:
        flash("This ticket does not require acknowledgement.", "error")
        return redirect(url_for("main.support_detail", ticket_code=ticket_code))
    if ticket.acknowledged_at is None:
        ticket.acknowledged_at = datetime.utcnow()
        ticket.updated_at = datetime.utcnow()
        db.session.commit()
        flash("Acknowledged.", "ok")
    return redirect(url_for("main.support_detail", ticket_code=ticket_code))


@main_bp.route("/admin/support")
@require_admin
def admin_support_inbox():
    show_archived = (request.args.get("show") or "").strip().lower() == "archived"

    ticket_query = SupportTicket.query.filter(SupportTicket.kind != "broadcast")
    if show_archived:
        ticket_query = ticket_query.filter(SupportTicket.archived.is_(True))
    else:
        ticket_query = ticket_query.filter(SupportTicket.archived.is_(False))
    tickets = ticket_query.order_by(SupportTicket.updated_at.desc()).all()

    unread_counts = dict(
        db.session.query(SupportMessage.ticket_id, func.count(SupportMessage.id))
        .filter(
            SupportMessage.sender_role == "user",
            SupportMessage.is_read_by_admin.is_(False),
        )
        .group_by(SupportMessage.ticket_id)
        .all()
    )

    broadcast_query = SupportTicket.query.filter(SupportTicket.kind == "broadcast")
    if show_archived:
        broadcast_query = broadcast_query.filter(SupportTicket.archived.is_(True))
    else:
        broadcast_query = broadcast_query.filter(SupportTicket.archived.is_(False))
    broadcast_tickets = broadcast_query.all()
    broadcast_groups = {}
    for ticket in broadcast_tickets:
        if not ticket.broadcast_id:
            continue
        group = broadcast_groups.get(ticket.broadcast_id)
        if not group:
            group = {
                "broadcast_id": ticket.broadcast_id,
                "subject": ticket.subject,
                "updated_at": ticket.updated_at,
                "total": 0,
                "acknowledged": 0,
                "archived_all": True,
            }
            broadcast_groups[ticket.broadcast_id] = group
        group["total"] += 1
        if ticket.acknowledged_at:
            group["acknowledged"] += 1
        if ticket.updated_at and ticket.updated_at > group["updated_at"]:
            group["updated_at"] = ticket.updated_at
        if not ticket.archived:
            group["archived_all"] = False

    broadcasts = sorted(
        broadcast_groups.values(),
        key=lambda g: g["updated_at"] or datetime.min,
        reverse=True
    )

    return render_template(
        "admin_support/index.html",
        tickets=tickets,
        unread_counts=unread_counts,
        broadcasts=broadcasts,
        show_archived=show_archived,
        cloudinary_enabled=cloudinary_enabled,
    )


@main_bp.route("/admin/support/broadcast", methods=["GET", "POST"])
@require_admin
def admin_support_broadcast():
    from qventory.models.user import User
    if request.method == "POST":
        subject = (request.form.get("subject") or "").strip()
        body = (request.form.get("body") or "").strip()
        target = (request.form.get("target") or "all").strip().lower()
        recipients_raw = (request.form.get("recipients") or "").strip()

        if not subject or not body:
            flash("Subject and message are required.", "error")
            return redirect(url_for("main.admin_support_broadcast"))

        users = []
        if target == "all":
            users = User.query.order_by(User.id.asc()).all()
        else:
            tokens = [t.strip() for t in recipients_raw.replace("\n", ",").split(",") if t.strip()]
            if not tokens:
                flash("Provide at least one username or email.", "error")
                return redirect(url_for("main.admin_support_broadcast"))
            users = User.query.filter(
                (User.email.in_(tokens)) | (User.username.in_(tokens))
            ).all()
            found = {u.email for u in users} | {u.username for u in users}
            missing = [t for t in tokens if t not in found]
            if missing:
                flash(f"Users not found: {', '.join(missing)}", "error")
                return redirect(url_for("main.admin_support_broadcast"))

        if not users:
            flash("No recipients found.", "error")
            return redirect(url_for("main.admin_support_broadcast"))

        broadcast_id = f"BRD-{datetime.utcnow().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
        created_count = 0
        email_failures = 0
        from qventory.helpers.email_sender import send_support_broadcast_email
        for user in users:
            ticket = SupportTicket(
                ticket_code=_support_ticket_code(),
                user_id=user.id,
                subject=subject[:200],
                status="open",
                kind="broadcast",
                broadcast_id=broadcast_id,
                requires_ack=True,
            )
            db.session.add(ticket)
            db.session.flush()
            message = SupportMessage(
                ticket_id=ticket.id,
                sender_role="admin",
                body=body,
                is_read_by_user=False,
                is_read_by_admin=True,
            )
            db.session.add(message)
            created_count += 1
            ticket_url = url_for("main.support_detail", ticket_code=ticket.ticket_code, _external=True)
            ok, _err = send_support_broadcast_email(
                user.email,
                user.username or user.email,
                subject,
                body,
                ticket_url,
            )
            if not ok:
                email_failures += 1

        db.session.commit()
        if email_failures:
            flash(f"Broadcast sent to {created_count} users. Email failures: {email_failures}.", "error")
        else:
            flash(f"Broadcast sent to {created_count} users.", "ok")
        return redirect(url_for("main.admin_support_inbox"))

    return render_template("admin_support/broadcast.html")


@main_bp.route("/admin/support/<ticket_code>")
@require_admin
def admin_support_detail(ticket_code):
    ticket = SupportTicket.query.filter_by(ticket_code=ticket_code).first_or_404()
    if ticket.kind == "broadcast" and ticket.broadcast_id:
        return redirect(url_for("main.admin_support_broadcast_detail", broadcast_id=ticket.broadcast_id))

    SupportMessage.query.filter_by(
        ticket_id=ticket.id,
        sender_role="user",
        is_read_by_admin=False
    ).update({"is_read_by_admin": True})
    db.session.commit()

    messages = ticket.messages.order_by(SupportMessage.created_at.asc()).all()

    return render_template(
        "admin_support/detail.html",
        ticket=ticket,
        messages=messages,
        cloudinary_enabled=cloudinary_enabled,
    )


@main_bp.route("/admin/support/<ticket_code>/message", methods=["POST"])
@require_admin
def admin_support_message(ticket_code):
    ticket = SupportTicket.query.filter_by(ticket_code=ticket_code).first_or_404()

    if ticket.status != "open":
        flash("This ticket is closed.", "error")
        return redirect(url_for("main.admin_support_detail", ticket_code=ticket_code))

    body = (request.form.get("body") or "").strip()
    if not body:
        flash("Message cannot be empty.", "error")
        return redirect(url_for("main.admin_support_detail", ticket_code=ticket_code))

    message = SupportMessage(
        ticket_id=ticket.id,
        sender_role="admin",
        body=body,
        is_read_by_user=False,
        is_read_by_admin=True,
    )
    db.session.add(message)
    db.session.flush()

    files = request.files.getlist("attachments")
    uploads, error = _upload_support_attachments(
        files, user_id=ticket.user_id, ticket_code=ticket.ticket_code
    )
    if error:
        db.session.rollback()
        flash(error, "error")
        return redirect(url_for("main.admin_support_detail", ticket_code=ticket_code))

    for item in uploads:
        db.session.add(SupportAttachment(
            message_id=message.id,
            image_url=item["url"],
            public_id=item.get("public_id"),
            filename=item.get("filename"),
            bytes=item.get("bytes"),
        ))

    ticket.updated_at = datetime.utcnow()
    db.session.commit()
    return redirect(url_for("main.admin_support_detail", ticket_code=ticket_code))


@main_bp.route("/admin/support/<ticket_code>/status", methods=["POST"])
@require_admin
def admin_support_status(ticket_code):
    ticket = SupportTicket.query.filter_by(ticket_code=ticket_code).first_or_404()
    status = (request.form.get("status") or "").strip().lower()
    if status not in {"resolved", "closed"}:
        flash("Invalid status.", "error")
        return redirect(url_for("main.admin_support_detail", ticket_code=ticket_code))

    now = datetime.utcnow()
    ticket.status = status
    if status == "resolved":
        ticket.resolved_at = now
    if status == "closed":
        ticket.closed_at = now
    ticket.updated_at = now
    db.session.commit()
    return redirect(url_for("main.admin_support_detail", ticket_code=ticket_code))


# ---------------------- Batch QR (protegido) ----------------------

@main_bp.route("/qr/batch", methods=["GET", "POST"])
@login_required
def qr_batch():
    s = get_or_create_settings(current_user)
    if request.method == "GET":
        labels = s.labels_map()
        enabled_levels = list(s.enabled_levels())

        rows = (
            Item.query.filter(
                Item.user_id == current_user.id,
                Item.is_active.is_(True),
                Item.inactive_by_user.is_(False)
            )
            .with_entities(Item.location_code)
            .filter(Item.location_code.isnot(None), Item.location_code != "")
            .distinct()
            .all()
        )
        location_codes = sorted({row[0] for row in rows if row[0]})
        total_location_items = len(location_codes)

        tree = {}
        for code in location_codes:
            parts = parse_location_code(code)
            current = tree
            accum = {}
            for level in enabled_levels:
                value = parts.get(level)
                if not value:
                    break
                accum[level] = value
                node = current.get(value)
                if not node:
                    node = {
                        "level": level,
                        "value": value,
                        "children": {},
                        "code": None,
                        "count": 0,
                    }
                    current[value] = node
                node["count"] += 1
                node["code"] = compose_location_code(
                    A=accum.get("A"),
                    B=accum.get("B"),
                    S=accum.get("S"),
                    C=accum.get("C"),
                    enabled=tuple(enabled_levels),
                )
                current = node["children"]

        return render_template(
            "batch_qr.html",
            settings=s,
            location_tree=tree,
            location_labels=labels,
            total_location_items=total_location_items,
        )

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


@main_bp.route("/qr/batch/print-selected", methods=["POST"])
@login_required
def qr_batch_print_selected():
    s = get_or_create_settings(current_user)
    codes = request.form.getlist("location_codes")
    codes = [c for c in codes if c]
    if not codes:
        flash("Select at least one location to print.", "error")
        return redirect(url_for("main.qr_batch"))

    from ..helpers.utils import build_qr_batch_pdf
    pdf_buf = build_qr_batch_pdf(
        codes, s,
        lambda code: url_for(
            "main.public_view_location",
            username=current_user.username,
            code=code,
            _external=True
        )
    )
    return send_file(pdf_buf, mimetype="application/pdf", as_attachment=True, download_name="qr_labels.pdf")


@main_bp.route("/qr/location/print/<code>")
@login_required
def qr_location_print(code):
    s = get_or_create_settings(current_user)
    link = url_for(
        "main.public_view_location",
        username=current_user.username,
        code=code,
        _external=True
    )
    pdf_bytes = _build_location_label_pdf(code, link)
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=False,
        download_name=f"qr_{code}.pdf"
    )


@main_bp.route("/qr/location/print/<code>/preview")
@login_required
def qr_location_print_preview(code):
    pdf_url = url_for("main.qr_location_print", code=code)
    return render_template(
        "print_label.html",
        item=None,
        pdf_url=pdf_url,
    )


# ---------------------- Rutas públicas por username ----------------------

@main_bp.route("/<username>/location/<code>")
def public_view_location(username, code):
    user = User.query.filter_by(username=username).first_or_404()
    s = get_or_create_settings(user)
    normalized_code = (code or "").strip()
    parts = parse_location_code(normalized_code)

    q = Item.query.filter(
        Item.user_id == user.id,
        Item.is_active.is_(True),
        Item.inactive_by_user.is_(False)
    )

    # Match explicit location_code to support eBay-imported SKUs without parsed A/B/S/C.
    code_filters = [Item.location_code == normalized_code]

    if parts:
        component_filters = []
        if s.enable_A and "A" in parts:
            component_filters.append(Item.A == parts["A"])
        if s.enable_B and "B" in parts:
            component_filters.append(Item.B == parts["B"])
        if s.enable_S and "S" in parts:
            component_filters.append(Item.S == parts["S"])
        if s.enable_C and "C" in parts:
            component_filters.append(Item.C == parts["C"])
        if component_filters:
            code_filters.append(db.and_(*component_filters))

    q = q.filter(db.or_(*code_filters))

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
    sitemap_url = f"{request.url_root.rstrip('/')}/sitemap.xml"
    body = f"User-agent: *\nAllow: /\nSitemap: {sitemap_url}\n"
    return Response(body, mimetype="text/plain")


@main_bp.route("/sitemap.xml")
def sitemap_xml():
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>{request.url_root.rstrip('/')}/</loc></url>
  <url><loc>{request.url_root.rstrip('/')}/pricing</loc></url>
  <url><loc>{request.url_root.rstrip('/')}/privacy</loc></url>
  <url><loc>{request.url_root.rstrip('/')}/login</loc></url>
  <url><loc>{request.url_root.rstrip('/')}/register</loc></url>
  <url><loc>{request.url_root.rstrip('/')}/forgot-password</loc></url>
  <url><loc>{request.url_root.rstrip('/')}/offline</loc></url>
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

    qr_size = 18 * mm
    gap_qr_text = 2 * mm
    x_qr = m
    y_qr = m + (inner_h - qr_size) / 2.0

    text_x = x_qr + qr_size + gap_qr_text
    text_w = W - m - text_x

    title = (it.title or "").strip()
    sku = (it.sku or "-").strip()

    def fit_font(text, font_name, base_size, min_size, max_width):
        size = base_size
        while size > min_size and c.stringWidth(text, font_name, size) > max_width:
            size -= 0.5
        return size

    def ellipsize_to_width(text, font_name, size, max_width):
        if c.stringWidth(text, font_name, size) <= max_width:
            return text
        ellipsis = "..."
        trimmed = text
        while trimmed and c.stringWidth(trimmed + ellipsis, font_name, size) > max_width:
            trimmed = trimmed[:-1]
        return (trimmed + ellipsis) if trimmed else ellipsis

    def wrap_text(text, font_name, size, max_width):
        words = text.split()
        if not words:
            return [""]
        lines = []
        current = words[0]
        for word in words[1:]:
            trial = f"{current} {word}"
            if c.stringWidth(trial, font_name, size) <= max_width:
                current = trial
            else:
                lines.append(current)
                current = word
        lines.append(current)
        return lines

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
    c.drawImage(ImageReader(qr_img), x_qr, y_qr, width=qr_size, height=qr_size, preserveAspectRatio=True)

    sku_fs = fit_font(sku, "Helvetica-Bold", 11, 8, text_w)
    sku_y = y_qr + 3 * mm

    available_title_height = (y_qr + qr_size) - (sku_y + sku_fs + 1 * mm)
    title_fs = min(8.5, max(6.0, available_title_height / 2.6))

    lines = wrap_text(title, "Helvetica-Bold", title_fs, text_w)
    line_height = title_fs * 1.15
    max_lines = max(1, int(available_title_height // line_height))

    while len(lines) > max_lines and title_fs > 6.0:
        title_fs -= 0.5
        lines = wrap_text(title, "Helvetica-Bold", title_fs, text_w)
        line_height = title_fs * 1.15
        max_lines = max(1, int(available_title_height // line_height))

    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = ellipsize_to_width(lines[-1], "Helvetica-Bold", title_fs, text_w)

    start_y = y_qr + qr_size - title_fs
    c.setFont("Helvetica-Bold", title_fs)
    for idx, line in enumerate(lines):
        c.drawString(text_x, start_y - (idx * line_height), line)

    c.setFont("Helvetica-Bold", sku_fs)
    c.drawString(text_x, sku_y, sku)

    c.showPage()
    c.save()
    pdf_bytes = buf.getvalue()
    buf.close()
    return pdf_bytes


def _build_location_label_pdf(code: str, link: str) -> bytes:
    W = 40 * mm
    H = 30 * mm

    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(W, H))

    m = 3 * mm
    inner_w = W - 2 * m
    inner_h = H - 2 * m

    qr_size = 18 * mm
    gap_qr_text = 2 * mm
    x_qr = m
    y_qr = m + (inner_h - qr_size) / 2.0

    text_x = x_qr + qr_size + gap_qr_text
    text_w = W - m - text_x

    def fit_font(text, font_name, base_size, min_size, max_width):
        size = base_size
        while size > min_size and c.stringWidth(text, font_name, size) > max_width:
            size -= 0.5
        return size

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=1,
    )
    qr.add_data(link)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white")
    if getattr(qr_img, "mode", None) != 'RGB':
        qr_img = qr_img.convert('RGB')
    c.drawImage(ImageReader(qr_img), x_qr, y_qr, width=qr_size, height=qr_size, preserveAspectRatio=True)

    text = f"Location: {code}"
    font_size = fit_font(text, "Helvetica-Bold", 12, 8, text_w)
    text_y = y_qr + (qr_size / 2.0) - (font_size / 2.0)
    c.setFont("Helvetica-Bold", font_size)
    c.drawString(text_x, text_y, text)

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


@main_bp.route("/item/<int:item_id>/print/pdf", methods=["GET"])
@login_required
def print_item_pdf(item_id):
    it = Item.query.filter_by(id=item_id, user_id=current_user.id).first_or_404()
    s = get_or_create_settings(current_user)
    pdf_bytes = _build_item_label_pdf(it, s)
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=False,
        download_name=f"label_{it.sku}.pdf",
    )


@main_bp.route("/item/<int:item_id>/print/preview", methods=["GET"])
@login_required
def print_item_preview(item_id):
    it = Item.query.filter_by(id=item_id, user_id=current_user.id).first_or_404()
    pdf_url = url_for("main.print_item_pdf", item_id=item_id)
    return render_template(
        "print_label.html",
        item=it,
        pdf_url=pdf_url,
    )


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


# ---------------------- Admin: Help Center ----------------------

def _slugify(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


@main_bp.route("/admin/help-center")
@require_admin
def admin_help_center():
    seed_help_articles()
    articles = HelpArticle.query.order_by(
        HelpArticle.display_order.asc(),
        HelpArticle.title.asc()
    ).all()
    return render_template("admin_help_center.html", articles=articles)


@main_bp.route("/admin/help-center/new", methods=["GET", "POST"])
@require_admin
def admin_help_center_new():
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        slug = (request.form.get("slug") or "").strip()
        summary = (request.form.get("summary") or "").strip() or None
        body_md = (request.form.get("body_md") or "").strip()
        display_order = int(request.form.get("display_order") or 0)
        is_published = request.form.get("is_published") == "on"

        if not title or not body_md:
            flash("Title and body are required.", "error")
            return redirect(url_for("main.admin_help_center_new"))

        if not slug:
            slug = _slugify(title)
        if HelpArticle.query.filter_by(slug=slug).first():
            flash("Slug already exists. Choose a different slug.", "error")
            return redirect(url_for("main.admin_help_center_new"))

        article = HelpArticle(
            slug=slug,
            title=title,
            summary=summary,
            body_md=body_md,
            display_order=display_order,
            is_published=is_published,
        )
        db.session.add(article)
        db.session.commit()
        flash("Help article created.", "ok")
        return redirect(url_for("main.admin_help_center_edit", article_id=article.id))

    return render_template(
        "admin_help_center_edit.html",
        article=None,
        is_new=True,
        form_action=url_for("main.admin_help_center_new"),
    )


@main_bp.route("/admin/help-center/<int:article_id>/edit", methods=["GET", "POST"])
@require_admin
def admin_help_center_edit(article_id):
    article = HelpArticle.query.get_or_404(article_id)
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        slug = (request.form.get("slug") or "").strip()
        summary = (request.form.get("summary") or "").strip() or None
        body_md = (request.form.get("body_md") or "").strip()
        display_order = int(request.form.get("display_order") or 0)
        is_published = request.form.get("is_published") == "on"

        if not title or not body_md:
            flash("Title and body are required.", "error")
            return redirect(url_for("main.admin_help_center_edit", article_id=article.id))

        if not slug:
            slug = _slugify(title)

        existing = HelpArticle.query.filter_by(slug=slug).first()
        if existing and existing.id != article.id:
            flash("Slug already exists. Choose a different slug.", "error")
            return redirect(url_for("main.admin_help_center_edit", article_id=article.id))

        article.title = title
        article.slug = slug
        article.summary = summary
        article.body_md = body_md
        article.display_order = display_order
        article.is_published = is_published
        db.session.commit()

        flash("Help article updated.", "ok")
        return redirect(url_for("main.admin_help_center_edit", article_id=article.id))

    return render_template(
        "admin_help_center_edit.html",
        article=article,
        is_new=False,
        form_action=url_for("main.admin_help_center_edit", article_id=article.id),
    )


@main_bp.route("/admin/help-center/upload-image", methods=["POST"])
@require_admin
def admin_help_center_upload_image():
    if not cloudinary_enabled:
        return jsonify({"ok": False, "error": "Cloudinary not configured"}), 503

    f = request.files.get("file")
    if not f:
        return jsonify({"ok": False, "error": "Missing file"}), 400

    ct = (f.mimetype or "").lower()
    if not ct.startswith("image/"):
        return jsonify({"ok": False, "error": "Only image files are allowed"}), 400

    f.seek(0, io.SEEK_END)
    size = f.tell()
    f.seek(0)
    if size > 2 * 1024 * 1024:
        return jsonify({"ok": False, "error": "Image too large (max 2MB)"}), 400

    try:
        up = cloudinary.uploader.upload(
            f,
            folder="qventory/help-center",
            overwrite=True,
            resource_type="image",
            transformation=[{"quality": "auto", "fetch_format": "auto"}]
        )
        url = up.get("secure_url") or up.get("url")
        return jsonify({"ok": True, "url": url})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 502


@main_bp.route("/admin/dashboard")
@require_admin
def admin_dashboard():
    """Admin dashboard - view all users and their inventory stats"""
    from qventory.models.system_setting import SystemSetting
    # Get all users with item count
    users = User.query.all()
    user_stats = []

    for user in users:
        item_count = Item.query.filter(
            Item.user_id == user.id,
            Item.is_active.is_(True),
            Item.inactive_by_user.is_(False)
        ).count()
        missing_cost_count = Item.query.filter(
            Item.user_id == user.id,
            Item.is_active.is_(True),
            Item.inactive_by_user.is_(False),
            Item.item_cost.is_(None)
        ).count()
        user_stats.append({
            'user': user,
            'item_count': item_count,
            'missing_cost_count': missing_cost_count,
            'has_inventory': item_count > 0
        })

    # Sort by item count descending
    user_stats.sort(key=lambda x: x['item_count'], reverse=True)

    heuristic_days = SystemSetting.get_int('delivery_heuristic_days', 7)
    trial_days = SystemSetting.get_int('stripe_trial_days', 10)
    return render_template(
        "admin_dashboard.html",
        user_stats=user_stats,
        heuristic_days=heuristic_days,
        trial_days=trial_days
    )


@main_bp.route("/admin/impersonate/<int:user_id>", methods=["POST"])
@require_admin
def admin_impersonate_user(user_id):
    user = User.query.get_or_404(user_id)
    login_user(user)
    session["impersonating"] = True
    session["impersonated_user_id"] = user.id
    flash(f"Impersonating {user.username}.", "ok")
    return redirect(url_for("main.dashboard"))


@main_bp.route("/admin/impersonate/stop", methods=["POST"])
@require_admin
def admin_stop_impersonation():
    session.pop("impersonating", None)
    session.pop("impersonated_user_id", None)
    logout_user()
    flash("Returned to admin panel.", "ok")
    return redirect(url_for("main.admin_dashboard"))


@main_bp.route("/admin/user/<int:user_id>/inventory-text")
@require_admin
def admin_user_inventory_text(user_id):
    user = User.query.get_or_404(user_id)
    items = (
        Item.query.filter(
            Item.user_id == user_id,
            Item.is_active.is_(True),
            Item.inactive_by_user.is_(False)
        )
        .order_by(Item.created_at.desc())
        .all()
    )
    return render_template(
        "admin_user_inventory_text.html",
        user=user,
        items=items
    )


@main_bp.route("/admin/user/<int:user_id>/diagnostics")
@require_admin
def admin_user_diagnostics(user_id):
    """View import diagnostics for a specific user"""
    from qventory.models.failed_import import FailedImport
    from qventory.models.import_job import ImportJob
    from qventory.models.marketplace_credential import MarketplaceCredential
    from qventory.models.polling_log import PollingLog

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

    # Get recent polling logs
    recent_polls = PollingLog.query.filter_by(user_id=user_id, marketplace='ebay').order_by(
        PollingLog.created_at.desc()
    ).limit(20).all()

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
        error_summary=error_summary,
        recent_polls=recent_polls
    )


@main_bp.route("/admin/polling-logs")
@require_admin
def admin_polling_logs():
    """Admin polling logs summary (batch view)."""
    from qventory.models.polling_log import PollingLog
    from qventory.models.user import User
    from qventory.models.system_setting import SystemSetting
    from datetime import datetime, timedelta
    import os

    interval_seconds = int(os.environ.get('POLL_INTERVAL_SECONDS', 300))
    now = datetime.utcnow()
    lookback = now - timedelta(hours=24)

    recent_logs = db.session.query(
        PollingLog,
        User.username
    ).join(
        User, PollingLog.user_id == User.id
    ).filter(
        PollingLog.created_at >= lookback,
        PollingLog.marketplace == 'ebay'
    ).order_by(
        PollingLog.created_at.desc()
    ).limit(300).all()

    def bucket_key(dt):
        ts = int(dt.timestamp())
        bucket = ts - (ts % interval_seconds)
        return datetime.utcfromtimestamp(bucket)

    buckets = {}
    for log, username in recent_logs:
        key = bucket_key(log.created_at)
        entry = buckets.setdefault(key, {
            'start': key,
            'end': key + timedelta(seconds=interval_seconds),
            'total': 0,
            'success': 0,
            'errors': 0,
            'new_listings': 0,
            'rate_limited': False,
            'error_samples': []
        })
        entry['total'] += 1
        if log.status == 'success':
            entry['success'] += 1
        else:
            entry['errors'] += 1
        entry['new_listings'] += log.new_listings or 0
        err = (log.error_message or '').lower()
        if 'rate limit' in err or 'exceeded usage limit' in err or 'call usage' in err or '429' in err:
            entry['rate_limited'] = True
        if log.error_message and len(entry['error_samples']) < 3:
            entry['error_samples'].append(log.error_message[:300])

    batch_rows = sorted(buckets.values(), key=lambda x: x['start'], reverse=True)[:30]
    cooldown_until_ts = SystemSetting.get_int('ebay_polling_cooldown_until')
    cooldown_until = None
    if cooldown_until_ts:
        try:
            cooldown_until = datetime.utcfromtimestamp(cooldown_until_ts)
        except Exception:
            cooldown_until = None

    return render_template(
        "admin_polling_logs.html",
        batch_rows=batch_rows,
        interval_seconds=interval_seconds,
        cooldown_until=cooldown_until
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
        subscription = user.get_subscription()
        today_usage = AITokenUsage.get_today_usage(user.id)
        token_limit = AITokenConfig.get_token_limit(user.role)

        user_data.append({
            'user': user,
            'subscription': subscription,
            'tokens_used_today': today_usage.tokens_used if today_usage else 0,
            'token_limit': token_limit,
            'tokens_remaining': token_limit - (today_usage.tokens_used if today_usage else 0)
        })

    return render_template("admin_user_roles.html", user_data=user_data)


@main_bp.route("/admin/users/roles/emails.txt")
@require_admin
def admin_users_roles_emails_txt():
    emails = [
        (u.email or "").strip().lower()
        for u in User.query.order_by(User.created_at.desc()).all()
        if (u.email or "").strip()
    ]
    content = ",".join(emails)
    resp = Response(content, mimetype="text/plain")
    resp.headers["Content-Disposition"] = "attachment; filename=emails.txt"
    return resp


@main_bp.route("/admin/user/<int:user_id>/role", methods=["POST"])
@require_admin
def admin_change_user_role(user_id):
    """Change a user's role"""
    user = User.query.get_or_404(user_id)
    new_role = request.form.get("role", "").strip().lower()

    valid_roles = ['free', 'early_adopter', 'premium', 'plus', 'pro', 'god', 'enterprise']
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


@main_bp.route("/admin/revive-recurring-expenses", methods=["POST"])
@require_admin
def admin_revive_recurring_expenses():
    """
    Manually trigger recurring expenses revival for users who had recurring expenses last month
    """
    from qventory.tasks import revive_recurring_expenses

    task = revive_recurring_expenses.delay()

    flash(
        f"Recurring expenses revive task launched (Task ID: {task.id}). "
        "This will create missing current-month entries for users with recurring expenses last month.",
        "ok"
    )
    return redirect(url_for('main.admin_dashboard'))


@main_bp.route("/admin/backfill-failed-payments", methods=["POST"])
@require_admin
def admin_backfill_failed_payments():
    """
    Manually trigger a backfill for failed Stripe payments after trial.
    """
    from qventory.tasks import backfill_failed_payments

    task = backfill_failed_payments.delay()

    flash(
        f"Backfill failed payments task launched (Task ID: {task.id}). "
        "This will downgrade users with past_due/unpaid Stripe status after trial and send emails.",
        "ok"
    )
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


@main_bp.route("/admin/refresh-ebay-user-ids", methods=["POST"])
@require_admin
def admin_refresh_ebay_user_ids():
    """Refresh eBay tokens and update ebay_user_id for all active accounts."""
    from qventory.tasks import refresh_ebay_user_ids_global

    task = refresh_ebay_user_ids_global.delay()
    flash(
        f"eBay user ID refresh task launched (Task ID: {task.id}). "
        "This will refresh tokens and update ebay_user_id when possible.",
        "ok"
    )
    return redirect(url_for('main.admin_dashboard'))


@main_bp.route("/admin/resync-all-inventory", methods=["POST"])
@require_admin
def admin_resync_all_inventory():
    """
    Global action: resync eBay inventory and backfill listing dates.
    """
    from qventory.tasks import resync_all_inventories_backfill_dates

    task = resync_all_inventories_backfill_dates.delay()
    flash(
        f"Resync task launched (Task ID: {task.id}). All eBay inventories will be synced and listing dates backfilled.",
        "ok"
    )
    return redirect(url_for('main.admin_dashboard'))


@main_bp.route("/admin/recalculate-analytics", methods=["POST"])
@require_admin
def admin_recalculate_analytics():
    """Global action: recalculate analytics using Orders + Finances APIs."""
    from qventory.tasks import recalculate_ebay_analytics_global

    task = recalculate_ebay_analytics_global.delay()
    flash(
        f"Analytics recalculation task launched (Task ID: {task.id}).",
        "ok"
    )
    return redirect(url_for('main.admin_dashboard'))


@main_bp.route("/admin/backfill-shipping-costs", methods=["POST"])
@require_admin
def admin_backfill_shipping_costs():
    """Global action: sync finances + reconcile to populate shipping label costs."""
    from qventory.tasks import backfill_shipping_costs_global

    task = backfill_shipping_costs_global.delay()
    flash(
        f"Shipping cost backfill task launched (Task ID: {task.id}). Finances will be synced and shipping costs reconciled for all accounts.",
        "ok"
    )
    return redirect(url_for('main.admin_dashboard'))


@main_bp.route("/admin/backfill-recent-prices", methods=["POST"])
@require_admin
def admin_backfill_recent_prices():
    """Backfill prices for all active items missing a price."""
    from qventory.tasks import backfill_recent_item_prices

    task = backfill_recent_item_prices.delay(hours=0)
    flash(
        f"Price backfill task launched (Task ID: {task.id}). "
        f"All active items without a price will be enriched via Trading API.",
        "ok"
    )
    return redirect(url_for('main.admin_dashboard'))


@main_bp.route("/admin/reconcile-user/<int:user_id>", methods=["POST"])
@require_admin
def admin_reconcile_user(user_id):
    """Reconcile finances + shipping costs for a single user via Celery."""
    from qventory.tasks import reconcile_user_finances

    user = User.query.get_or_404(user_id)
    task = reconcile_user_finances.delay(user_id)
    flash(f"Reconciliation task launched for {user.username} (Task ID: {task.id}).", "ok")
    return redirect(request.referrer or url_for('main.admin_dashboard'))


@main_bp.route("/admin/delivery-heuristic", methods=["POST"])
@require_admin
def admin_update_delivery_heuristic():
    from qventory.models.system_setting import SystemSetting

    raw_value = request.form.get("delivery_heuristic_days", "").strip()
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        flash("Invalid heuristic value", "error")
        return redirect(url_for('main.admin_dashboard'))

    if value < 1 or value > 60:
        flash("Heuristic must be between 1 and 60 days", "error")
        return redirect(url_for('main.admin_dashboard'))

    setting = SystemSetting.query.filter_by(key='delivery_heuristic_days').first()
    if not setting:
        setting = SystemSetting(key='delivery_heuristic_days', value_int=value)
        db.session.add(setting)
    else:
        setting.value_int = value
    db.session.commit()

    flash("Delivery heuristic updated", "ok")
    return redirect(url_for('main.admin_dashboard'))


@main_bp.route("/admin/stripe-trial-days", methods=["POST"])
@require_admin
def admin_update_stripe_trial_days():
    from qventory.models.system_setting import SystemSetting

    raw_value = request.form.get("stripe_trial_days", "").strip()
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        flash("Invalid trial days value", "error")
        return redirect(url_for('main.admin_dashboard'))

    if value < 0 or value > 60:
        flash("Trial days must be between 0 and 60", "error")
        return redirect(url_for('main.admin_dashboard'))

    setting = SystemSetting.query.filter_by(key='stripe_trial_days').first()
    if not setting:
        setting = SystemSetting(key='stripe_trial_days', value_int=value)
        db.session.add(setting)
    else:
        setting.value_int = value
    db.session.commit()

    flash("Stripe trial days updated", "ok")
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

        # Monthly price (optional)
        price_str = request.form.get("monthly_price", "").strip()
        if price_str == "":
            plan_limit.monthly_price = None
        else:
            plan_limit.monthly_price = float(price_str)
            if plan_limit.monthly_price < 0:
                raise ValueError("Monthly price must be positive")

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
    embed = request.args.get("embed") == "1"
    try:
        from qventory.models.system_setting import SystemSetting
        from qventory.tasks import sync_ebay_category_fee_catalog

        started = SystemSetting.query.filter_by(key='ebay_category_fee_sync_started').first()
        if not started:
            started = SystemSetting(
                key='ebay_category_fee_sync_started',
                value_int=int(datetime.utcnow().timestamp())
            )
            db.session.add(started)
            db.session.commit()
            sync_ebay_category_fee_catalog.delay(user_id=current_user.id)
    except Exception:
        db.session.rollback()
    return render_template("profit_calculator.html", embed=embed)


@main_bp.route("/api/ebay/categories/search")
@login_required
def api_ebay_category_search():
    q = (request.args.get("q") or "").strip()
    if not q or len(q) < 2:
        return jsonify({"ok": True, "categories": []})

    # Lazy sync if empty (best-effort)
    if EbayCategory.query.count() == 0:
        try:
            from ..helpers.ebay_taxonomy import sync_ebay_categories
            sync_ebay_categories()
        except Exception as e:
            return jsonify({"ok": False, "error": f"Category sync failed: {e}"}), 500

    like = f"%{q}%"
    categories = (
        EbayCategory.query.filter(
            or_(
                EbayCategory.name.ilike(like),
                EbayCategory.full_path.ilike(like)
            )
        )
        .order_by(EbayCategory.is_leaf.desc(), EbayCategory.full_path.asc())
        .limit(20)
        .all()
    )

    return jsonify({
        "ok": True,
        "categories": [c.to_dict() for c in categories],
    })


@main_bp.route("/api/ebay/categories")
@login_required
def api_ebay_categories():
    leaf_only = request.args.get("leaf_only", "1") == "1"

    if EbayCategory.query.count() == 0:
        try:
            from ..helpers.ebay_taxonomy import sync_ebay_categories
            sync_ebay_categories()
        except Exception as e:
            return jsonify({"ok": False, "error": f"Category sync failed: {e}"}), 500

    q = EbayCategory.query
    if leaf_only:
        q = q.filter(EbayCategory.is_leaf.is_(True))

    categories = q.order_by(EbayCategory.full_path.asc()).all()
    return jsonify({"ok": True, "categories": [c.to_dict() for c in categories]})


@main_bp.route("/api/ebay/fees/estimate")
@login_required
def api_ebay_fee_estimate():
    category_id = request.args.get("category_id")
    has_store = request.args.get("has_store", "0") == "1"
    top_rated = request.args.get("top_rated", "0") == "1"
    price = request.args.get("price")
    shipping_cost = request.args.get("shipping_cost", "0")
    try:
        price_val = float(price) if price is not None else 0.0
        shipping_val = float(shipping_cost)
    except ValueError:
        return jsonify({"ok": False, "error": "Invalid price inputs"}), 400

    rule = None
    if category_id:
        rule = EbayFeeRule.query.filter_by(category_id=category_id).first()
    if not rule:
        rule = EbayFeeRule.query.filter_by(category_id=None).first()
    if rule:
        rate = rule.resolve_rate(has_store=has_store, top_rated=top_rated)
        response = {"ok": True, "fee_rate_percent": rate}
        if price_val > 0:
            fee_base = price_val + shipping_val
            response["total_fees"] = round(fee_base * (rate / 100), 2)
        return jsonify(response)

    from ..helpers.ebay_fee_live import get_live_fee_estimate
    live = get_live_fee_estimate(
        user_id=current_user.id,
        category_id=category_id,
        price=price_val,
        shipping_cost=shipping_val,
        has_store=has_store,
        top_rated=top_rated
    )
    if live.get("success"):
        return jsonify({
            "ok": True,
            "fee_rate_percent": live["fee_rate_percent"],
            "total_fees": live["total_fees"],
            "fees": live["fees"]
        })

    return jsonify({"ok": False, "error": live.get("error") or "Missing eBay fee rules"}), 400


@main_bp.route("/api/profit-calculator/calc", methods=["POST"])
@login_required
def api_profit_calculator_calc():
    payload = request.get_json(silent=True) or {}
    marketplace = (payload.get("marketplace") or "ebay").strip().lower()

    item_name = (payload.get("item_name") or "").strip()
    buy_price = float(payload.get("buy_price") or 0)
    resale_price = float(payload.get("resale_price") or 0)
    shipping_cost = float(payload.get("shipping_cost") or 0)
    ads_fee_rate = float(payload.get("ads_fee_rate") or 0)

    if buy_price <= 0 or resale_price <= 0:
        return jsonify({"ok": False, "error": "Invalid price inputs."}), 400

    fee_breakdown = {}
    category_id = payload.get("category_id")
    category_path = payload.get("category_path")

    if marketplace == "ebay":
        from ..helpers.ebay_fees import estimate_ebay_fees
        from ..helpers.ebay_fee_live import get_live_fee_estimate
        has_store = bool(payload.get("has_store"))
        top_rated = bool(payload.get("top_rated"))
        include_fixed_fee = bool(payload.get("include_fixed_fee"))

        live = get_live_fee_estimate(
            user_id=current_user.id,
            category_id=category_id,
            price=resale_price,
            shipping_cost=shipping_cost,
            has_store=has_store,
            top_rated=top_rated
        )

        if live.get("success"):
            fee_breakdown = {
                "fee_rate_percent": live["fee_rate_percent"],
                "marketplace_fee": live["total_fees"],
                "fixed_fee": 0.0,
                "ads_fee": resale_price * (ads_fee_rate / 100),
                "total_fees": live["total_fees"] + (resale_price * (ads_fee_rate / 100)),
                "fees": live["fees"],
                "source": "trading_api_verify_add_fixed_price_item"
            }
        else:
            fee_breakdown = estimate_ebay_fees(
                category_id=category_id,
                resale_price=resale_price,
                shipping_cost=shipping_cost,
                has_store=has_store,
                top_rated=top_rated,
                include_fixed_fee=include_fixed_fee,
                ads_fee_rate=ads_fee_rate,
            )

        total_fees = fee_breakdown["total_fees"]
        net_sale = resale_price - total_fees - shipping_cost
        profit = net_sale - buy_price
        roi = (profit / buy_price * 100) if buy_price else 0
        markup = ((resale_price - buy_price) / buy_price * 100) if buy_price else 0
        denom = 1 - ((fee_breakdown["fee_rate_percent"] + ads_fee_rate) / 100)
        breakeven = ((buy_price + shipping_cost + fee_breakdown.get("fixed_fee", 0)) / denom) if denom > 0 else 0

        fee_lines = []
        for fee in fee_breakdown.get("fees", [])[:6]:
            fee_lines.append(f"- {fee['name']}: ${fee['amount']:.2f}")
        fee_block = "\n".join(fee_lines) if fee_lines else "Fees calculated from eBay fee rules."

        output_text = "\n".join([
            f"🧾 Item: {item_name or 'Unnamed'}",
            f"🏪 Marketplace: eBay",
            f"📁 Category: {category_path or 'Unselected'}",
            f"💰 Profit: ${profit:.2f}",
            f"🔄 ROI: {roi:.2f}%",
            f"📊 Markup: {markup:.2f}%",
            f"📦 Net Sale: ${net_sale:.2f}",
            f"💸 eBay Fees (estimated): ${fee_breakdown['marketplace_fee']:.2f}",
            f"📣 Ads Fee ({ads_fee_rate:.2f}%): ${fee_breakdown['ads_fee']:.2f}",
            f"🚚 Shipping Cost: ${shipping_cost:.2f}",
            f"🧮 Break-even Price: ${breakeven:.2f}",
            f"📚 Fee Breakdown:\n{fee_block}",
        ])
    else:
        return jsonify({"ok": False, "error": "Unsupported marketplace for API calc."}), 400

    report = ProfitCalculatorReport(
        user_id=current_user.id,
        marketplace=marketplace,
        item_name=item_name,
        category_id=category_id,
        category_path=category_path,
        buy_price=buy_price,
        resale_price=resale_price,
        shipping_cost=shipping_cost,
        has_store=bool(payload.get("has_store")),
        top_rated=bool(payload.get("top_rated")),
        include_fixed_fee=bool(payload.get("include_fixed_fee")),
        ads_fee_rate=ads_fee_rate,
        fee_breakdown=fee_breakdown,
        total_fees=total_fees,
        net_sale=net_sale,
        profit=profit,
        roi=roi,
        markup=markup,
        breakeven=breakeven,
        output_text=output_text,
    )
    db.session.add(report)
    db.session.commit()

    return jsonify({
        "ok": True,
        "report": report.to_dict(),
        "output_text": output_text,
        "fee_breakdown": fee_breakdown,
    })


@main_bp.route("/api/profit-calculator/reports")
@login_required
def api_profit_calculator_reports():
    reports = (
        ProfitCalculatorReport.query.filter_by(user_id=current_user.id)
        .order_by(ProfitCalculatorReport.created_at.desc())
        .limit(50)
        .all()
    )
    return jsonify({"ok": True, "reports": [r.to_dict() for r in reports]})


@main_bp.route("/api/profit-calculator/reports/<int:report_id>", methods=["DELETE"])
@login_required
def api_profit_calculator_delete_report(report_id):
    report = ProfitCalculatorReport.query.filter_by(
        id=report_id,
        user_id=current_user.id
    ).first()
    if not report:
        return jsonify({"ok": False, "error": "Report not found"}), 404
    db.session.delete(report)
    db.session.commit()
    return jsonify({"ok": True})


@main_bp.route("/admin/ebay/categories/sync", methods=["POST"])
@require_admin
def admin_sync_ebay_categories():
    from ..helpers.ebay_taxonomy import sync_ebay_categories
    result = sync_ebay_categories()
    return jsonify({"ok": True, "result": result})


@main_bp.route("/admin/ebay/fees/import", methods=["POST"])
@require_admin
def admin_import_ebay_fees():
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "Missing CSV file"}), 400
    file = request.files["file"]
    if not file.filename:
        return jsonify({"ok": False, "error": "Empty filename"}), 400
    from ..helpers.ebay_fee_import import import_ebay_fee_rules_csv
    result = import_ebay_fee_rules_csv(file)
    return jsonify({"ok": True, "result": result})


@main_bp.route("/api/autocomplete-items")
@login_required
def api_autocomplete_items():
    """Autocomplete items by title, SKU, or supplier"""
    q = (request.args.get("q") or "").strip()
    view_type = request.args.get("view_type", "active")  # active, sold, ended
    exclude_ids_raw = (request.args.get("exclude_ids") or "").strip()

    if not q or len(q) < 2:
        return jsonify({"ok": True, "items": []})

    like = f"%{q}%"

    # Build query based on view_type
    query = Item.query.filter_by(user_id=current_user.id)

    # Filter by view type
    if view_type == "active":
        query = query.filter(Item.is_active == True, Item.inactive_by_user.is_(False))
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

    if exclude_ids_raw:
        exclude_ids = []
        for part in exclude_ids_raw.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                exclude_ids.append(int(part))
            except ValueError:
                continue
        if exclude_ids:
            query = query.filter(~Item.id.in_(exclude_ids))

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


@main_bp.route("/api/items/<int:item_id>/cost-history")
@login_required
def api_item_cost_history(item_id):
    """Return cost history for an item (expenses + receipt items)."""
    from qventory.models.item import Item
    from qventory.models.expense import Expense
    from qventory.models.receipt_item import ReceiptItem
    from qventory.models.item_cost_history import ItemCostHistory

    item = Item.query.filter_by(id=item_id, user_id=current_user.id).first()
    if not item:
        return jsonify({"ok": False, "error": "Item not found"}), 404

    expenses = Expense.query.filter_by(user_id=current_user.id, item_id=item_id).order_by(
        Expense.item_cost_applied_at.desc().nullslast(),
        Expense.created_at.desc()
    ).all()

    receipt_items = ReceiptItem.query.filter_by(
        inventory_item_id=item_id
    ).order_by(
        ReceiptItem.associated_at.desc().nullslast(),
        ReceiptItem.created_at.desc()
    ).all()

    manual_history = ItemCostHistory.query.filter_by(
        user_id=current_user.id,
        item_id=item_id
    ).order_by(ItemCostHistory.created_at.desc()).all()

    expense_rows = []
    for exp in expenses:
        expense_rows.append({
            "id": exp.id,
            "description": exp.description,
            "amount": float(exp.amount) if exp.amount is not None else None,
            "category": exp.category,
            "expense_date": exp.expense_date.isoformat() if exp.expense_date else None,
            "applied_at": exp.item_cost_applied_at.isoformat() if exp.item_cost_applied_at else None,
            "notes": exp.notes
        })

    receipt_rows = []
    for ri in receipt_items:
        receipt = ri.receipt
        receipt_rows.append({
            "id": ri.id,
            "description": ri.final_description,
            "amount": float(ri.final_total_price) if ri.final_total_price is not None else None,
            "unit_price": float(ri.final_unit_price) if ri.final_unit_price is not None else None,
            "quantity": ri.final_quantity,
            "associated_at": ri.associated_at.isoformat() if ri.associated_at else None,
            "receipt_date": receipt.receipt_date.isoformat() if receipt and receipt.receipt_date else None,
            "merchant_name": receipt.merchant_name if receipt else None
        })

    manual_rows = []
    for entry in manual_history:
        manual_rows.append({
            "id": entry.id,
            "previous_cost": entry.previous_cost,
            "new_cost": entry.new_cost,
            "delta": entry.delta,
            "note": entry.note,
            "created_at": entry.created_at.isoformat() if entry.created_at else None
        })

    return jsonify({
        "ok": True,
        "item": {"id": item.id, "title": item.title},
        "expenses": expense_rows,
        "receipt_items": receipt_rows,
        "manual_changes": manual_rows
    })


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

    # STEP 1: Fetch real eBay sold listings
    print("📡 Fetching eBay sold listings...", file=sys.stderr)
    from qventory.helpers.ebay_api_scraper import get_sold_listings_ebay_api, format_listings_for_ai

    scraped_data = get_sold_listings_ebay_api(item_title, max_results=10, days_back=7)
    print(f"✓ Found {scraped_data.get('count', 0)} sold listings", file=sys.stderr)

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
                'link': item['link'],
                'sold_date': item.get('sold_date', ''),
                'condition': item.get('condition', '')
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
    pickup_unread_count = Notification.query.filter_by(
        user_id=current_user.id,
        is_read=False,
        source="pickup"
    ).count()

    return jsonify({
        "ok": True,
        "notifications": [n.to_dict() for n in notifications],
        "unread_count": unread_count,
        "pickup_unread_count": pickup_unread_count
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


@main_bp.route("/<slug>")
def public_link_bio(slug):
    if "." in slug:
        abort(404)
    slug_norm = (slug or "").strip().lower()
    if not slug_norm:
        abort(404)

    settings = Setting.query.filter(
        Setting.link_bio_slug == slug_norm
    ).first()

    user = None
    if settings:
        user = User.query.filter_by(id=settings.user_id).first()
    else:
        user = User.query.filter(func.lower(User.username) == slug_norm).first()
        if user:
            settings = Setting.query.filter_by(user_id=user.id).first()

    if not user or not settings:
        abort(404)

    from qventory.models.marketplace_credential import MarketplaceCredential
    ebay_cred = MarketplaceCredential.query.filter_by(
        user_id=user.id,
        marketplace='ebay',
        is_active=True
    ).first()
    ebay_link = None
    if ebay_cred and ebay_cred.ebay_user_id:
        ebay_link = f"https://www.ebay.com/str/{ebay_cred.ebay_user_id}"

    import json
    links = []
    if ebay_link:
        links.append({"label": "eBay", "url": ebay_link})

    stored_links = []
    if settings.link_bio_links_json:
        try:
            stored_links = json.loads(settings.link_bio_links_json) or []
        except Exception:
            stored_links = []

    def infer_label(url):
        host = urlparse(url).netloc.lower()
        if "poshmark" in host:
            return "Poshmark"
        if "etsy" in host:
            return "Etsy"
        if "mercari" in host:
            return "Mercari"
        if "depop" in host:
            return "Depop"
        if "whatnot" in host:
            return "Whatnot"
        if "vinted" in host:
            return "Vinted"
        if "amazon" in host:
            return "Amazon"
        return "Shop"

    for link in stored_links:
        url = (link.get("url") or "").strip()
        if not url:
            continue
        label = (link.get("label") or "").strip()
        if not label or label.lower() in {"shop", "store", "link"}:
            label = infer_label(url)
        links.append({"label": label, "url": url})

    featured_ids = []
    if settings.link_bio_featured_json:
        try:
            featured_ids = json.loads(settings.link_bio_featured_json) or []
        except Exception:
            featured_ids = []

    featured_items = []
    if featured_ids:
        items = (
            Item.query.filter(
                Item.user_id == user.id,
                Item.is_active.is_(True),
                Item.inactive_by_user.is_(False),
                Item.id.in_(featured_ids)
            ).all()
        )
        items_by_id = {item.id: item for item in items}
        for item_id in featured_ids:
            item = items_by_id.get(item_id)
            if item:
                featured_items.append(item)

    def listing_url(item):
        return (
            item.listing_link
            or item.ebay_url
            or item.web_url
            or item.poshmark_url
            or item.mercari_url
            or item.depop_url
            or item.whatnot_url
            or item.vinted_url
            or item.amazon_url
        )

    featured_cards = []
    for item in featured_items:
        featured_cards.append({
            "title": item.title,
            "price": item.item_price,
            "image": item.item_thumb,
            "url": listing_url(item)
        })

    display_name = user.username
    return render_template(
        "link_bio.html",
        user=user,
        settings=settings,
        links=links,
        featured_cards=featured_cards,
        display_name=display_name
    )
@main_bp.route("/admin/support/broadcast/<broadcast_id>")
@require_admin
def admin_support_broadcast_detail(broadcast_id):
    ticket = SupportTicket.query.filter_by(broadcast_id=broadcast_id, kind="broadcast").order_by(SupportTicket.created_at.asc()).first_or_404()
    messages = ticket.messages.order_by(SupportMessage.created_at.asc()).all()
    total = SupportTicket.query.filter_by(broadcast_id=broadcast_id).count()
    acknowledged = SupportTicket.query.filter(
        SupportTicket.broadcast_id == broadcast_id,
        SupportTicket.acknowledged_at.isnot(None)
    ).count()
    return render_template(
        "admin_support/broadcast_detail.html",
        ticket=ticket,
        messages=messages,
        broadcast_stats={"total": total, "acknowledged": acknowledged},
    )


@main_bp.route("/admin/support/archive", methods=["POST"])
@require_admin
def admin_support_archive():
    targets = request.form.getlist("archive_targets")
    if not targets:
        flash("Select at least one ticket or broadcast to archive.", "error")
        return redirect(url_for("main.admin_support_inbox"))

    for token in targets:
        if token.startswith("ticket:"):
            try:
                ticket_id = int(token.split(":", 1)[1])
            except ValueError:
                continue
            SupportTicket.query.filter_by(id=ticket_id).update({"archived": True})
        elif token.startswith("broadcast:"):
            broadcast_id = token.split(":", 1)[1]
            SupportTicket.query.filter_by(broadcast_id=broadcast_id).update({"archived": True})

    db.session.commit()
    flash("Selected items archived.", "ok")
    return redirect(url_for("main.admin_support_inbox"))
