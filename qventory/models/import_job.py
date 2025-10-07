"""
ImportJob Model - Track background import tasks
"""
from datetime import datetime
from qventory.extensions import db


class ImportJob(db.Model):
    """Track eBay import jobs running in background"""
    __tablename__ = 'import_jobs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # Job tracking
    celery_task_id = db.Column(db.String(255), unique=True, index=True)
    status = db.Column(db.String(50), default='pending', index=True)
    # Status: pending, processing, completed, failed

    # Import settings
    import_mode = db.Column(db.String(50))  # new_only, update_existing, sync_all
    listing_status = db.Column(db.String(50))  # ACTIVE, ALL

    # Progress tracking
    total_items = db.Column(db.Integer, default=0)
    processed_items = db.Column(db.Integer, default=0)
    imported_count = db.Column(db.Integer, default=0)
    updated_count = db.Column(db.Integer, default=0)
    skipped_count = db.Column(db.Integer, default=0)
    error_count = db.Column(db.Integer, default=0)

    # Error tracking
    error_message = db.Column(db.Text)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    notified = db.Column(db.Boolean, default=False)

    # Relationship
    user = db.relationship('User', backref=db.backref('import_jobs', lazy='dynamic'))

    def __repr__(self):
        return f'<ImportJob {self.id} user={self.user_id} status={self.status}>'

    def to_dict(self):
        """Serialize to JSON"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'celery_task_id': self.celery_task_id,
            'status': self.status,
            'import_mode': self.import_mode,
            'listing_status': self.listing_status,
            'total_items': self.total_items,
            'processed_items': self.processed_items,
            'imported_count': self.imported_count,
            'updated_count': self.updated_count,
            'skipped_count': self.skipped_count,
            'error_count': self.error_count,
            'error_message': self.error_message,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'notified': self.notified,
            'progress_percent': int((self.processed_items / self.total_items * 100)) if self.total_items > 0 else 0
        }

    @staticmethod
    def cleanup_old_jobs(days=30):
        """Delete completed/failed jobs older than X days"""
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(days=days)

        old_jobs = ImportJob.query.filter(
            ImportJob.status.in_(['completed', 'failed']),
            ImportJob.created_at < cutoff
        ).all()

        for job in old_jobs:
            db.session.delete(job)

        db.session.commit()
        return len(old_jobs)
