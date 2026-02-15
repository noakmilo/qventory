from datetime import datetime
from ..extensions import db


class EbayFeeSnapshot(db.Model):
    __tablename__ = "ebay_fee_snapshots"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    category_id = db.Column(db.String(64), nullable=True, index=True)
    price = db.Column(db.Float, nullable=False)
    shipping_cost = db.Column(db.Float, default=0.0)
    has_store = db.Column(db.Boolean, default=False)
    top_rated = db.Column(db.Boolean, default=False)

    fee_rate_percent = db.Column(db.Float, default=0.0)
    total_fees = db.Column(db.Float, default=0.0)
    fee_breakdown = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    user = db.relationship("User", backref="ebay_fee_snapshots")
