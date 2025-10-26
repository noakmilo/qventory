"""
Receipt model for storing uploaded receipt images and their OCR metadata.
"""
from datetime import datetime
from qventory.extensions import db


class Receipt(db.Model):
    """
    Represents an uploaded receipt with OCR-extracted data.

    Status flow:
    - pending: Just uploaded, OCR processing not started
    - processing: OCR extraction in progress
    - extracted: OCR completed successfully, awaiting user review
    - partially_associated: Some items mapped to inventory/expenses
    - completed: All items processed
    - discarded: User marked as irrelevant
    - failed: OCR extraction failed
    """
    __tablename__ = 'receipts'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    # Image storage
    image_url = db.Column(db.String(500), nullable=False)  # Cloudinary URL
    image_public_id = db.Column(db.String(255), nullable=False)  # Cloudinary public ID for deletion
    thumbnail_url = db.Column(db.String(500))  # Thumbnail for list view

    # OCR data
    ocr_provider = db.Column(db.String(50))  # 'google_vision', 'tesseract', 'mock', etc.
    ocr_raw_text = db.Column(db.Text)  # Full extracted text
    ocr_confidence = db.Column(db.Float)  # Average confidence score (0-1)
    ocr_processed_at = db.Column(db.DateTime)
    ocr_error_message = db.Column(db.Text)

    # Extracted receipt metadata
    merchant_name = db.Column(db.String(255))
    receipt_date = db.Column(db.Date)
    receipt_number = db.Column(db.String(100))
    subtotal = db.Column(db.Numeric(10, 2))
    tax_amount = db.Column(db.Numeric(10, 2))
    total_amount = db.Column(db.Numeric(10, 2))
    currency = db.Column(db.String(3), default='USD')

    # Status tracking
    status = db.Column(
        db.String(50),
        nullable=False,
        default='pending',
        index=True
    )  # pending, processing, extracted, partially_associated, completed, discarded, failed

    # User notes and metadata
    notes = db.Column(db.Text)
    original_filename = db.Column(db.String(255))  # Original upload filename
    file_size = db.Column(db.Integer)  # Size in bytes

    # Timestamps
    uploaded_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    last_reviewed_at = db.Column(db.DateTime)  # Last time user opened/reviewed
    completed_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = db.relationship('User', backref=db.backref('receipts', lazy='dynamic'))
    items = db.relationship(
        'ReceiptItem',
        backref='receipt',
        lazy='dynamic',
        cascade='all, delete-orphan'
    )
    usage_record = db.relationship(
        'ReceiptUsage',
        back_populates='receipt',
        uselist=False,
        cascade='all, delete-orphan',
        single_parent=True
    )

    def __repr__(self):
        return f'<Receipt {self.id} - {self.merchant_name} - {self.status}>'

    @property
    def items_count(self):
        """Total number of extracted items."""
        return self.items.count()

    @property
    def associated_items_count(self):
        """Number of items associated with inventory or expenses."""
        # Import here to avoid circular dependency
        from qventory.models.receipt_item import ReceiptItem
        return self.items.filter(
            db.or_(
                ReceiptItem.inventory_item_id.isnot(None),
                ReceiptItem.expense_id.isnot(None)
            )
        ).count()

    @property
    def association_progress(self):
        """Percentage of items associated (0-100)."""
        total = self.items_count
        if total == 0:
            return 100
        return int((self.associated_items_count / total) * 100)

    def update_status(self):
        """
        Auto-update status based on associations.
        Call after adding/removing associations.
        """
        if self.status in ['pending', 'processing', 'failed', 'discarded']:
            return  # Don't auto-update these statuses

        total = self.items_count
        associated = self.associated_items_count

        if total == 0:
            self.status = 'extracted'
        elif associated == 0:
            self.status = 'extracted'
        elif associated < total:
            self.status = 'partially_associated'
        else:
            self.status = 'completed'
            if not self.completed_at:
                self.completed_at = datetime.utcnow()

    def to_dict(self):
        """Serialize receipt for JSON responses."""
        return {
            'id': self.id,
            'merchant_name': self.merchant_name,
            'receipt_date': self.receipt_date.isoformat() if self.receipt_date else None,
            'total_amount': float(self.total_amount) if self.total_amount else None,
            'status': self.status,
            'image_url': self.image_url,
            'thumbnail_url': self.thumbnail_url,
            'items_count': self.items_count,
            'associated_items_count': self.associated_items_count,
            'association_progress': self.association_progress,
            'uploaded_at': self.uploaded_at.isoformat(),
            'last_reviewed_at': self.last_reviewed_at.isoformat() if self.last_reviewed_at else None,
        }
