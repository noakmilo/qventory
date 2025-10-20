"""
Webhook Settings Routes
UI for managing webhook subscriptions
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from qventory.extensions import db
from qventory.models.webhook import WebhookSubscription
from qventory.helpers.webhook_helpers import get_webhook_stats

webhook_settings_bp = Blueprint('webhook_settings', __name__, url_prefix='/settings/webhooks')


@webhook_settings_bp.route('/', methods=['GET'])
@login_required
def webhook_settings():
    """
    Webhook management dashboard
    Shows all subscriptions, stats, and allows management
    """
    # Get user's subscriptions
    subscriptions = WebhookSubscription.query.filter_by(
        user_id=current_user.id
    ).order_by(WebhookSubscription.created_at.desc()).all()

    # Get webhook stats
    stats = get_webhook_stats(current_user.id)

    return render_template(
        'settings/webhooks.html',
        subscriptions=subscriptions,
        stats=stats
    )
