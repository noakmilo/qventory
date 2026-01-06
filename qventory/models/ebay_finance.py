from datetime import datetime

from qventory.extensions import db


class EbayPayout(db.Model):
    __tablename__ = 'ebay_payouts'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    external_id = db.Column(db.String(64), nullable=False)
    payout_id = db.Column(db.String(64))
    payout_date = db.Column(db.DateTime)
    status = db.Column(db.String(40))
    gross_amount = db.Column(db.Numeric(12, 2), default=0)
    fee_amount = db.Column(db.Numeric(12, 2), default=0)
    net_amount = db.Column(db.Numeric(12, 2), default=0)
    currency = db.Column(db.String(10))
    raw_json = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'external_id', name='uq_ebay_payouts_user_external'),
        db.Index('idx_ebay_payouts_user_date', 'user_id', 'payout_date'),
    )


class EbayFinanceTransaction(db.Model):
    __tablename__ = 'ebay_finance_transactions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    external_id = db.Column(db.String(64), nullable=False)
    transaction_id = db.Column(db.String(64))
    transaction_date = db.Column(db.DateTime)
    transaction_type = db.Column(db.String(40))
    amount = db.Column(db.Numeric(12, 2), default=0)
    currency = db.Column(db.String(10))
    order_id = db.Column(db.String(64))
    reference_id = db.Column(db.String(64))
    raw_json = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'external_id', name='uq_ebay_fin_tx_user_external'),
        db.Index('idx_ebay_fin_tx_user_date', 'user_id', 'transaction_date'),
    )
