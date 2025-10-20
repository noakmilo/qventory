"""
Admin Webhook Debug Console
For administrators to monitor webhook system health
"""
from flask import Blueprint, render_template, jsonify, request
from flask_login import login_required, current_user
from qventory.extensions import db
from qventory.models.webhook import WebhookSubscription, WebhookEvent, WebhookProcessingQueue
from qventory.models.user import User
from datetime import datetime, timedelta
from sqlalchemy import func

admin_webhooks_bp = Blueprint('admin_webhooks', __name__, url_prefix='/admin/webhooks')


def is_admin():
    """Check if current user is admin"""
    # You can implement your own admin check logic here
    # For now, checking if user has 'admin' role or is specific user
    return current_user.is_authenticated and (
        current_user.role == 'admin' or
        current_user.username == 'admin'
    )


@admin_webhooks_bp.route('/', methods=['GET'])
@login_required
def webhook_console():
    """
    Webhook debug console - Admin only
    Shows webhook events, subscriptions, and system health
    """
    if not is_admin():
        return "Unauthorized - Admin access required", 403

    return render_template('admin_webhooks_console.html')


@admin_webhooks_bp.route('/api/events', methods=['GET'])
@login_required
def get_recent_events():
    """
    Get recent webhook events (last 100)
    """
    if not is_admin():
        return jsonify({'error': 'Unauthorized'}), 403

    # Get query parameters
    limit = int(request.args.get('limit', 100))
    status = request.args.get('status')  # pending, completed, failed
    topic = request.args.get('topic')

    # Build query
    query = WebhookEvent.query

    if status:
        query = query.filter_by(status=status)
    if topic:
        query = query.filter_by(topic=topic)

    # Get events
    events = query.order_by(
        WebhookEvent.received_at.desc()
    ).limit(limit).all()

    return jsonify({
        'events': [
            {
                'id': e.id,
                'event_id': e.event_id,
                'topic': e.topic,
                'status': e.status,
                'user_id': e.user_id,
                'received_at': e.received_at.isoformat() if e.received_at else None,
                'processed_at': e.processed_at.isoformat() if e.processed_at else None,
                'processing_attempts': e.processing_attempts,
                'error_message': e.error_message
            }
            for e in events
        ],
        'total': len(events)
    }), 200


@admin_webhooks_bp.route('/api/subscriptions', methods=['GET'])
@login_required
def get_all_subscriptions():
    """
    Get all webhook subscriptions across all users
    """
    if not is_admin():
        return jsonify({'error': 'Unauthorized'}), 403

    # Get subscriptions with user info
    subscriptions = db.session.query(
        WebhookSubscription,
        User.username,
        User.email
    ).join(
        User, WebhookSubscription.user_id == User.id
    ).order_by(
        WebhookSubscription.created_at.desc()
    ).all()

    return jsonify({
        'subscriptions': [
            {
                'id': sub.id,
                'user_id': sub.user_id,
                'username': username,
                'email': email,
                'topic': sub.topic,
                'status': sub.status,
                'subscription_id': sub.subscription_id,
                'created_at': sub.created_at.isoformat() if sub.created_at else None,
                'expires_at': sub.expires_at.isoformat() if sub.expires_at else None,
                'is_expired': sub.is_expired(),
                'needs_renewal': sub.needs_renewal(),
                'event_count': sub.event_count,
                'error_count': sub.error_count,
                'last_error_message': sub.last_error_message
            }
            for sub, username, email in subscriptions
        ],
        'total': len(subscriptions)
    }), 200


@admin_webhooks_bp.route('/api/stats', methods=['GET'])
@login_required
def get_webhook_stats():
    """
    Get overall webhook system statistics
    """
    if not is_admin():
        return jsonify({'error': 'Unauthorized'}), 403

    # Total subscriptions by status
    sub_stats = db.session.query(
        WebhookSubscription.status,
        func.count(WebhookSubscription.id)
    ).group_by(WebhookSubscription.status).all()

    # Total events by status
    event_stats = db.session.query(
        WebhookEvent.status,
        func.count(WebhookEvent.id)
    ).group_by(WebhookEvent.status).all()

    # Events by topic
    topic_stats = db.session.query(
        WebhookEvent.topic,
        func.count(WebhookEvent.id)
    ).group_by(WebhookEvent.topic).order_by(
        func.count(WebhookEvent.id).desc()
    ).limit(10).all()

    # Recent activity (last 24 hours)
    last_24h = datetime.utcnow() - timedelta(hours=24)
    events_last_24h = WebhookEvent.query.filter(
        WebhookEvent.received_at >= last_24h
    ).count()

    # Subscriptions expiring soon (within 2 days)
    expiring_soon = WebhookSubscription.query.filter(
        WebhookSubscription.expires_at < datetime.utcnow() + timedelta(days=2),
        WebhookSubscription.status == 'ENABLED'
    ).count()

    # Failed events in last 24h
    failed_last_24h = WebhookEvent.query.filter(
        WebhookEvent.received_at >= last_24h,
        WebhookEvent.status == 'failed'
    ).count()

    return jsonify({
        'subscriptions': {
            'by_status': dict(sub_stats),
            'total': sum(count for _, count in sub_stats),
            'expiring_soon': expiring_soon
        },
        'events': {
            'by_status': dict(event_stats),
            'total': sum(count for _, count in event_stats),
            'last_24h': events_last_24h,
            'failed_last_24h': failed_last_24h
        },
        'topics': {
            'top_topics': [
                {'topic': topic, 'count': count}
                for topic, count in topic_stats
            ]
        },
        'timestamp': datetime.utcnow().isoformat()
    }), 200


@admin_webhooks_bp.route('/api/errors', methods=['GET'])
@login_required
def get_recent_errors():
    """
    Get recent webhook errors
    """
    if not is_admin():
        return jsonify({'error': 'Unauthorized'}), 403

    limit = int(request.args.get('limit', 50))

    # Get failed events
    errors = WebhookEvent.query.filter_by(
        status='failed'
    ).order_by(
        WebhookEvent.received_at.desc()
    ).limit(limit).all()

    return jsonify({
        'errors': [
            {
                'id': e.id,
                'event_id': e.event_id,
                'topic': e.topic,
                'user_id': e.user_id,
                'error_message': e.error_message,
                'error_details': e.error_details,
                'received_at': e.received_at.isoformat() if e.received_at else None,
                'processing_attempts': e.processing_attempts
            }
            for e in errors
        ],
        'total': len(errors)
    }), 200


@admin_webhooks_bp.route('/api/queue', methods=['GET'])
@login_required
def get_processing_queue():
    """
    Get current processing queue status
    """
    if not is_admin():
        return jsonify({'error': 'Unauthorized'}), 403

    # Get queue items
    queue_items = WebhookProcessingQueue.query.order_by(
        WebhookProcessingQueue.priority.asc(),
        WebhookProcessingQueue.created_at.asc()
    ).limit(100).all()

    return jsonify({
        'queue': [
            {
                'id': q.id,
                'event_id': q.event_id,
                'priority': q.priority,
                'status': q.status,
                'retry_count': q.retry_count,
                'max_retries': q.max_retries,
                'next_retry_at': q.next_retry_at.isoformat() if q.next_retry_at else None,
                'created_at': q.created_at.isoformat() if q.created_at else None,
                'celery_task_id': q.celery_task_id
            }
            for q in queue_items
        ],
        'total': len(queue_items)
    }), 200
