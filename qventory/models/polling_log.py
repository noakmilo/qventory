"""
PollingLog Model - Track polling history per user
"""
from datetime import datetime
from qventory.extensions import db


class PollingLog(db.Model):
    """Track polling runs for marketplace syncs"""
    __tablename__ = 'polling_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    marketplace = db.Column(db.String(50), default='ebay', index=True)

    started_at = db.Column(db.DateTime)
    ended_at = db.Column(db.DateTime)
    window_start = db.Column(db.DateTime)
    window_end = db.Column(db.DateTime)

    new_listings = db.Column(db.Integer, default=0)
    errors_count = db.Column(db.Integer, default=0)
    error_message = db.Column(db.Text)
    status = db.Column(db.String(20), default='success', index=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    user = db.relationship('User', backref=db.backref('polling_logs', lazy='dynamic'))

    def __repr__(self):
        return f'<PollingLog {self.id} user={self.user_id} status={self.status}>'
