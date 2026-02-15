from datetime import datetime
from ..extensions import db


class EbayFeeRule(db.Model):
    __tablename__ = "ebay_fee_rules"

    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.String(64), nullable=True, index=True)
    standard_rate = db.Column(db.Float, nullable=False)
    store_rate = db.Column(db.Float, nullable=True)
    top_rated_discount = db.Column(db.Float, default=10.0)
    fixed_fee = db.Column(db.Float, default=0.30)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def resolve_rate(self, has_store=False, top_rated=False):
        rate = self.standard_rate
        if has_store and self.store_rate is not None:
            rate = self.store_rate
        if top_rated and self.top_rated_discount:
            rate *= (1 - (self.top_rated_discount / 100))
        return rate
