"""
User Notification Model
Stores notifications for background tasks and system events
"""
from datetime import datetime
from qventory.extensions import db


class Notification(db.Model):
    """
    User notifications for background tasks, system events, etc.
    """
    __tablename__ = 'notifications'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)

    # Notification details
    type = db.Column(db.String(50), nullable=False)  # 'success', 'error', 'warning', 'info'
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text)

    # Optional link
    link_url = db.Column(db.String(500))
    link_text = db.Column(db.String(100))

    # Metadata
    source = db.Column(db.String(50))  # 'import', 'relist', 'sync', etc.
    is_read = db.Column(db.Boolean, default=False, index=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    read_at = db.Column(db.DateTime)

    # Relationships
    user = db.relationship('User', backref=db.backref('notifications', lazy='dynamic'))

    def __repr__(self):
        return f'<Notification {self.id}: {self.type} for user {self.user_id}>'

    def mark_as_read(self):
        """Mark notification as read"""
        if not self.is_read:
            self.is_read = True
            self.read_at = datetime.utcnow()
            db.session.commit()

    def to_dict(self):
        """Convert to dictionary for JSON responses"""
        return {
            'id': self.id,
            'type': self.type,
            'title': self.title,
            'message': self.message,
            'link_url': self.link_url,
            'link_text': self.link_text,
            'source': self.source,
            'is_read': self.is_read,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'read_at': self.read_at.isoformat() if self.read_at else None
        }

    @staticmethod
    def create_notification(user_id, type, title, message=None, link_url=None, link_text=None, source=None):
        """
        Create a new notification

        Args:
            user_id: User ID
            type: 'success', 'error', 'warning', 'info'
            title: Notification title
            message: Optional detailed message
            link_url: Optional URL to link to
            link_text: Text for the link
            source: Source of notification (e.g., 'import', 'relist')

        Returns:
            Notification object
        """
        notification = Notification(
            user_id=user_id,
            type=type,
            title=title,
            message=message,
            link_url=link_url,
            link_text=link_text,
            source=source
        )
        db.session.add(notification)
        db.session.commit()
        return notification

    @staticmethod
    def get_unread_count(user_id):
        """Get count of unread notifications for user"""
        return Notification.query.filter_by(user_id=user_id, is_read=False).count()

    @staticmethod
    def get_recent(user_id, limit=10, include_read=False):
        """Get recent notifications for user"""
        query = Notification.query.filter_by(user_id=user_id)

        if not include_read:
            query = query.filter_by(is_read=False)

        return query.order_by(Notification.created_at.desc()).limit(limit).all()

    @staticmethod
    def mark_all_as_read(user_id):
        """Mark all notifications as read for user"""
        Notification.query.filter_by(user_id=user_id, is_read=False).update({
            'is_read': True,
            'read_at': datetime.utcnow()
        })
        db.session.commit()
