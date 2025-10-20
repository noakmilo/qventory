"""
eBay Webhook Models
Handles webhook subscriptions, events, and processing queue
"""
from qventory.extensions import db
from datetime import datetime, timedelta
import json


class WebhookSubscription(db.Model):
    """
    Tracks active webhook subscriptions for each user
    eBay webhooks expire after 7 days and need renewal
    """
    __tablename__ = 'webhook_subscriptions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # eBay subscription details
    subscription_id = db.Column(db.String(100), unique=True, nullable=False)  # eBay's subscription ID
    topic = db.Column(db.String(100), nullable=False)  # e.g., 'MARKETPLACE_ACCOUNT_DELETION', 'ITEM_SOLD', etc.
    status = db.Column(db.String(50), default='ENABLED')  # ENABLED, DISABLED, EXPIRED

    # Expiration tracking
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)  # eBay subscriptions expire after 7 days
    last_renewed_at = db.Column(db.DateTime)
    renewal_attempts = db.Column(db.Integer, default=0)

    # Configuration
    delivery_url = db.Column(db.String(500), nullable=False)  # Our webhook endpoint
    filter_criteria = db.Column(db.JSON)  # Optional filters for events

    # Monitoring
    event_count = db.Column(db.Integer, default=0)  # Total events received
    last_event_at = db.Column(db.DateTime)
    error_count = db.Column(db.Integer, default=0)
    last_error_at = db.Column(db.DateTime)
    last_error_message = db.Column(db.Text)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = db.relationship('User', backref='webhook_subscriptions')
    events = db.relationship('WebhookEvent', back_populates='subscription', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<WebhookSubscription {self.id}: {self.topic} for user {self.user_id}>'

    def is_expired(self):
        """Check if subscription has expired"""
        return datetime.utcnow() > self.expires_at

    def needs_renewal(self, days_before=2):
        """Check if subscription needs renewal (within X days of expiration)"""
        threshold = datetime.utcnow() + timedelta(days=days_before)
        return threshold > self.expires_at

    def mark_event_received(self):
        """Increment event counter and update last event time"""
        self.event_count += 1
        self.last_event_at = datetime.utcnow()
        db.session.commit()

    def mark_error(self, error_message):
        """Record an error"""
        self.error_count += 1
        self.last_error_at = datetime.utcnow()
        self.last_error_message = error_message
        db.session.commit()

    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            'id': self.id,
            'subscription_id': self.subscription_id,
            'topic': self.topic,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'is_expired': self.is_expired(),
            'needs_renewal': self.needs_renewal(),
            'event_count': self.event_count,
            'last_event_at': self.last_event_at.isoformat() if self.last_event_at else None,
            'error_count': self.error_count
        }


class WebhookEvent(db.Model):
    """
    Logs all webhook events received from eBay
    Keeps complete history for debugging and replay
    """
    __tablename__ = 'webhook_events'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # Nullable for events where user cannot be determined
    subscription_id = db.Column(db.Integer, db.ForeignKey('webhook_subscriptions.id'))

    # Event identification
    event_id = db.Column(db.String(100), unique=True, nullable=False)  # eBay's unique event ID
    topic = db.Column(db.String(100), nullable=False)  # Event type

    # Event data
    payload = db.Column(db.JSON, nullable=False)  # Full event payload from eBay
    headers = db.Column(db.JSON)  # HTTP headers (for debugging)

    # Processing status
    status = db.Column(db.String(50), default='pending')  # pending, processing, completed, failed
    processed_at = db.Column(db.DateTime)
    processing_attempts = db.Column(db.Integer, default=0)

    # Error handling
    error_message = db.Column(db.Text)
    error_details = db.Column(db.JSON)

    # Timestamps
    received_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    ebay_timestamp = db.Column(db.DateTime)  # Timestamp from eBay event

    # Relationships
    user = db.relationship('User', backref='webhook_events')
    subscription = db.relationship('WebhookSubscription', back_populates='events')

    def __repr__(self):
        return f'<WebhookEvent {self.id}: {self.topic} - {self.status}>'

    def mark_processing(self):
        """Mark event as being processed"""
        self.status = 'processing'
        self.processing_attempts += 1
        db.session.commit()

    def mark_completed(self):
        """Mark event as successfully processed"""
        self.status = 'completed'
        self.processed_at = datetime.utcnow()
        db.session.commit()

    def mark_failed(self, error_message, error_details=None):
        """Mark event as failed"""
        self.status = 'failed'
        self.error_message = error_message
        self.error_details = error_details
        self.processed_at = datetime.utcnow()
        db.session.commit()

    def can_retry(self, max_attempts=3):
        """Check if event can be retried"""
        return self.status == 'failed' and self.processing_attempts < max_attempts

    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            'id': self.id,
            'event_id': self.event_id,
            'topic': self.topic,
            'status': self.status,
            'received_at': self.received_at.isoformat() if self.received_at else None,
            'processed_at': self.processed_at.isoformat() if self.processed_at else None,
            'processing_attempts': self.processing_attempts,
            'error_message': self.error_message
        }


class WebhookProcessingQueue(db.Model):
    """
    Queue for processing webhook events asynchronously
    Ensures events are processed in order and with retry logic
    """
    __tablename__ = 'webhook_processing_queue'

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('webhook_events.id'), nullable=False)

    # Queue management
    priority = db.Column(db.Integer, default=5)  # 1=highest, 10=lowest
    status = db.Column(db.String(50), default='queued')  # queued, processing, completed, failed

    # Retry logic
    max_retries = db.Column(db.Integer, default=3)
    retry_count = db.Column(db.Integer, default=0)
    next_retry_at = db.Column(db.DateTime)

    # Celery task tracking
    celery_task_id = db.Column(db.String(100))

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)

    # Relationships
    event = db.relationship('WebhookEvent', backref='queue_entries')

    def __repr__(self):
        return f'<WebhookProcessingQueue {self.id}: Event {self.event_id} - {self.status}>'

    def mark_processing(self, celery_task_id=None):
        """Mark as being processed"""
        self.status = 'processing'
        self.started_at = datetime.utcnow()
        if celery_task_id:
            self.celery_task_id = celery_task_id
        db.session.commit()

    def mark_completed(self):
        """Mark as completed"""
        self.status = 'completed'
        self.completed_at = datetime.utcnow()
        db.session.commit()

    def mark_failed_with_retry(self):
        """Mark as failed and schedule retry"""
        self.retry_count += 1

        if self.retry_count >= self.max_retries:
            self.status = 'failed'
        else:
            self.status = 'queued'
            # Exponential backoff: 5min, 15min, 45min
            delay_minutes = 5 * (3 ** self.retry_count)
            self.next_retry_at = datetime.utcnow() + timedelta(minutes=delay_minutes)

        db.session.commit()

    def can_process(self):
        """Check if item can be processed now"""
        if self.status != 'queued':
            return False

        if self.next_retry_at and datetime.utcnow() < self.next_retry_at:
            return False

        return True
