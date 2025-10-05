"""
AI Research Report Model
Stores AI-generated market research reports with 24hr expiration
"""
from datetime import datetime, timedelta
from qventory import db


class Report(db.Model):
    """AI Research Report"""
    __tablename__ = 'reports'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # Report metadata
    item_title = db.Column(db.String(255), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey('items.id'), nullable=True)  # Optional reference
    status = db.Column(db.String(20), default='processing')  # processing, completed, failed

    # Report data
    scraped_count = db.Column(db.Integer, default=0)
    result_html = db.Column(db.Text, nullable=True)
    examples_json = db.Column(db.Text, nullable=True)  # JSON string with examples
    error_message = db.Column(db.Text, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=False)

    # Notification tracking
    viewed = db.Column(db.Boolean, default=False)
    notified = db.Column(db.Boolean, default=False)

    # Relationships
    user = db.relationship('User', backref='reports')
    item = db.relationship('Item', backref='reports', foreign_keys=[item_id])

    def __init__(self, **kwargs):
        super(Report, self).__init__(**kwargs)
        # Set expiration to 24 hours from now
        if not self.expires_at:
            self.expires_at = datetime.utcnow() + timedelta(hours=24)

    def to_dict(self):
        """Convert report to dictionary"""
        return {
            'id': self.id,
            'item_title': self.item_title,
            'item_id': self.item_id,
            'status': self.status,
            'scraped_count': self.scraped_count,
            'result_html': self.result_html,
            'examples_json': self.examples_json,
            'error_message': self.error_message,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'viewed': self.viewed,
            'notified': self.notified,
            'is_new': not self.viewed
        }

    @staticmethod
    def cleanup_expired():
        """Delete expired reports (older than 24hrs)"""
        expired = Report.query.filter(Report.expires_at < datetime.utcnow()).all()
        for report in expired:
            db.session.delete(report)
        db.session.commit()
        return len(expired)

    @staticmethod
    def get_unread_count(user_id):
        """Get count of unread reports for a user"""
        return Report.query.filter_by(
            user_id=user_id,
            viewed=False,
            status='completed'
        ).count()

    @staticmethod
    def get_user_reports(user_id, limit=20):
        """Get user's reports (non-expired, newest first)"""
        return Report.query.filter(
            Report.user_id == user_id,
            Report.expires_at > datetime.utcnow()
        ).order_by(Report.created_at.desc()).limit(limit).all()
