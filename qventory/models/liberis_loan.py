"""
Liberis Loan Model
Tracks eBay Seller Capital loans (Liberis partnership) with automatic repayment tracking
"""
from datetime import datetime, date
from qventory.extensions import db


class LiberisLoan(db.Model):
    """
    Tracks Liberis loan repayment via sales percentage
    Used for eBay Seller Capital program where Liberis charges a percentage on each sale
    """
    __tablename__ = 'liberis_loans'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)

    # Loan terms
    percentage = db.Column(db.Float, nullable=False)  # e.g., 17.0 for 17%
    start_date = db.Column(db.Date, nullable=False)  # Date when repayment started
    total_amount = db.Column(db.Float, nullable=False)  # Total amount to repay

    # Tracking
    paid_amount = db.Column(db.Float, nullable=False, default=0)  # Amount already paid
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)  # Whether loan is active

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)  # When loan was fully paid

    # Relationships
    user = db.relationship('User', backref=db.backref('liberis_loans', lazy='dynamic'))

    def __repr__(self):
        return f'<LiberisLoan {self.id}: User {self.user_id} - {self.percentage}% - ${self.paid_amount:.2f}/${self.total_amount:.2f}>'

    @property
    def remaining_amount(self):
        """Calculate remaining amount to pay"""
        return max(0, self.total_amount - self.paid_amount)

    @property
    def progress_percentage(self):
        """Calculate progress percentage (0-100)"""
        if self.total_amount == 0:
            return 100
        return min(100, (self.paid_amount / self.total_amount) * 100)

    @property
    def is_paid_off(self):
        """Check if loan is fully paid"""
        return self.paid_amount >= self.total_amount

    def calculate_fee_for_sale(self, sale_amount):
        """
        Calculate the Liberis fee for a given sale amount

        Args:
            sale_amount: The gross sale amount

        Returns:
            The fee amount to be paid to Liberis
        """
        if not self.is_active:
            return 0

        return sale_amount * (self.percentage / 100)

    def add_payment(self, amount):
        """
        Add a payment to the loan (called when a sale is made)

        Args:
            amount: The payment amount (percentage of sale)
        """
        self.paid_amount += amount
        self.updated_at = datetime.utcnow()

        # Auto-complete if paid off
        if self.is_paid_off and self.is_active:
            self.is_active = False
            self.completed_at = datetime.utcnow()

        db.session.commit()

    def recalculate_paid_amount(self):
        """
        Recalculate paid_amount based on all sales since start_date
        Useful for syncing after data changes
        """
        from qventory.models.sale import Sale

        # Include all valid sale statuses (exclude only cancelled, refunded, returned)
        sales = Sale.query.filter(
            Sale.user_id == self.user_id,
            Sale.sold_at >= datetime.combine(self.start_date, datetime.min.time()),
            Sale.status.notin_(['cancelled', 'refunded', 'returned'])
        ).all()

        total_paid = 0
        for sale in sales:
            fee = self.calculate_fee_for_sale(sale.sold_price)
            total_paid += fee

        self.paid_amount = min(total_paid, self.total_amount)
        self.updated_at = datetime.utcnow()

        # Auto-complete if paid off
        if self.is_paid_off and self.is_active:
            self.is_active = False
            self.completed_at = datetime.utcnow()

        db.session.commit()

    @staticmethod
    def get_active_loan(user_id):
        """
        Get the active Liberis loan for a user

        Args:
            user_id: The user ID

        Returns:
            LiberisLoan object or None
        """
        return LiberisLoan.query.filter_by(
            user_id=user_id,
            is_active=True
        ).first()

    @staticmethod
    def create_loan(user_id, percentage, start_date, total_amount):
        """
        Create a new Liberis loan

        Args:
            user_id: User ID
            percentage: Percentage fee (e.g., 17.0 for 17%)
            start_date: Date when repayment starts
            total_amount: Total amount to repay

        Returns:
            LiberisLoan object
        """
        # Deactivate any existing active loans
        existing_loans = LiberisLoan.query.filter_by(
            user_id=user_id,
            is_active=True
        ).all()

        for loan in existing_loans:
            loan.is_active = False
            loan.updated_at = datetime.utcnow()

        # Create new loan
        loan = LiberisLoan(
            user_id=user_id,
            percentage=percentage,
            start_date=start_date,
            total_amount=total_amount,
            paid_amount=0,
            is_active=True
        )
        db.session.add(loan)
        db.session.commit()

        # Calculate initial paid amount based on existing sales
        loan.recalculate_paid_amount()

        return loan
