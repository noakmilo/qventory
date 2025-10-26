"""
ReceiptItem model for individual line items extracted from receipts.
"""
from datetime import datetime
from qventory.extensions import db


class ReceiptItem(db.Model):
    """
    Individual line item extracted from a receipt via OCR.

    Can be associated with:
    - An inventory Item (tracking cost)
    - An Expense record (non-inventory costs)
    - Neither (unprocessed/skipped)
    """
    __tablename__ = 'receipt_items'

    id = db.Column(db.Integer, primary_key=True)
    receipt_id = db.Column(db.Integer, db.ForeignKey('receipts.id'), nullable=False, index=True)

    # OCR extracted data
    line_number = db.Column(db.Integer)  # Position in receipt (1, 2, 3...)
    description = db.Column(db.String(500))  # Item description from OCR
    quantity = db.Column(db.Integer, default=1)
    unit_price = db.Column(db.Numeric(10, 2))
    total_price = db.Column(db.Numeric(10, 2))
    ocr_confidence = db.Column(db.Float)  # Confidence for this line (0-1)

    # User corrections/overrides
    user_description = db.Column(db.String(500))  # User can override OCR text
    user_quantity = db.Column(db.Integer)
    user_unit_price = db.Column(db.Numeric(10, 2))
    user_total_price = db.Column(db.Numeric(10, 2))

    # Associations (mutually exclusive - either inventory OR expense)
    inventory_item_id = db.Column(db.Integer, db.ForeignKey('items.id'), index=True)
    expense_id = db.Column(db.Integer, db.ForeignKey('expenses.id'), index=True)

    # Status
    is_associated = db.Column(db.Boolean, default=False, index=True)
    is_skipped = db.Column(db.Boolean, default=False)  # User marked as "skip"
    notes = db.Column(db.Text)

    # Timestamps
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    associated_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    inventory_item = db.relationship('Item', backref=db.backref('receipt_items', lazy='dynamic'))
    expense = db.relationship('Expense', backref=db.backref('receipt_items', lazy='dynamic'))

    __table_args__ = (
        db.CheckConstraint(
            '(inventory_item_id IS NULL AND expense_id IS NULL) OR '
            '(inventory_item_id IS NOT NULL AND expense_id IS NULL) OR '
            '(inventory_item_id IS NULL AND expense_id IS NOT NULL)',
            name='check_single_association'
        ),
    )

    def __repr__(self):
        return f'<ReceiptItem {self.id} - {self.final_description}>'

    @property
    def final_description(self):
        """Get user-corrected description or fall back to OCR."""
        return self.user_description or self.description or 'Unknown item'

    @property
    def final_quantity(self):
        """Get user-corrected quantity or fall back to OCR."""
        return self.user_quantity or self.quantity or 1

    @property
    def final_unit_price(self):
        """Get user-corrected unit price or fall back to OCR."""
        return self.user_unit_price or self.unit_price

    @property
    def final_total_price(self):
        """Get user-corrected total or fall back to OCR."""
        return self.user_total_price or self.total_price

    @property
    def association_type(self):
        """Return 'inventory', 'expense', or None."""
        if self.inventory_item_id:
            return 'inventory'
        elif self.expense_id:
            return 'expense'
        return None

    def associate_with_inventory(self, item_id, update_cost=True):
        """
        Associate this receipt item with an inventory item.

        Args:
            item_id: ID of the inventory Item
            update_cost: If True, update the item's cost with receipt price
        """
        from qventory.models.item import Item

        # Clear any existing association
        self.inventory_item_id = None
        self.expense_id = None

        # Set new association
        self.inventory_item_id = item_id
        self.is_associated = True
        self.associated_at = datetime.utcnow()

        # Optionally update item cost
        if update_cost and self.final_unit_price:
            item = Item.query.get(item_id)
            if item:
                item.item_cost = self.final_unit_price
                item.updated_at = datetime.utcnow()

    def associate_with_expense(self, expense_id):
        """Associate this receipt item with an expense record."""
        # Clear any existing association
        self.inventory_item_id = None
        self.expense_id = None

        # Set new association
        self.expense_id = expense_id
        self.is_associated = True
        self.associated_at = datetime.utcnow()

    def clear_association(self):
        """Remove association with inventory/expense."""
        self.inventory_item_id = None
        self.expense_id = None
        self.is_associated = False
        self.associated_at = None

    def to_dict(self):
        """Serialize for JSON responses."""
        return {
            'id': self.id,
            'receipt_id': self.receipt_id,
            'line_number': self.line_number,
            'description': self.final_description,
            'quantity': self.final_quantity,
            'unit_price': float(self.final_unit_price) if self.final_unit_price else None,
            'total_price': float(self.final_total_price) if self.final_total_price else None,
            'ocr_confidence': self.ocr_confidence,
            'is_associated': self.is_associated,
            'is_skipped': self.is_skipped,
            'association_type': self.association_type,
            'inventory_item_id': self.inventory_item_id,
            'expense_id': self.expense_id,
            'notes': self.notes,
        }
