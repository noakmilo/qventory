"""
FailedImport Model - Track items that failed to import from eBay
"""
from datetime import datetime
from qventory.extensions import db


class FailedImport(db.Model):
    """Track eBay items that failed to import"""
    __tablename__ = 'failed_imports'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    import_job_id = db.Column(db.Integer, db.ForeignKey('import_jobs.id'), nullable=True)

    # Item identification
    ebay_listing_id = db.Column(db.String(50), index=True)
    ebay_title = db.Column(db.String(500))
    ebay_sku = db.Column(db.String(100))

    # Error details
    error_type = db.Column(db.String(50))  # parsing_error, api_error, timeout, etc.
    error_message = db.Column(db.Text)
    raw_data = db.Column(db.Text)  # Store raw XML/JSON for debugging

    # Retry tracking
    retry_count = db.Column(db.Integer, default=0)
    last_retry_at = db.Column(db.DateTime)
    resolved = db.Column(db.Boolean, default=False)
    resolved_at = db.Column(db.DateTime)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = db.relationship('User', backref=db.backref('failed_imports', lazy='dynamic'))
    import_job = db.relationship('ImportJob', backref=db.backref('failed_imports', lazy='dynamic'))

    def __repr__(self):
        return f'<FailedImport {self.id} listing={self.ebay_listing_id} error={self.error_type}>'

    def to_dict(self):
        """Serialize to JSON"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'import_job_id': self.import_job_id,
            'ebay_listing_id': self.ebay_listing_id,
            'ebay_title': self.ebay_title,
            'ebay_sku': self.ebay_sku,
            'error_type': self.error_type,
            'error_message': self.error_message,
            'retry_count': self.retry_count,
            'last_retry_at': self.last_retry_at.isoformat() if self.last_retry_at else None,
            'resolved': self.resolved,
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

    @staticmethod
    def get_unresolved_for_user(user_id):
        """Get all unresolved failed imports for a user"""
        return FailedImport.query.filter_by(
            user_id=user_id,
            resolved=False
        ).order_by(FailedImport.created_at.desc()).all()

    @staticmethod
    def cleanup_old_resolved(days=90):
        """Delete resolved failed imports older than X days"""
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(days=days)

        old_items = FailedImport.query.filter(
            FailedImport.resolved == True,
            FailedImport.resolved_at < cutoff
        ).all()

        for item in old_items:
            db.session.delete(item)

        db.session.commit()
        return len(old_items)
