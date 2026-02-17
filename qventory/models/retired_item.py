from datetime import datetime
from ..extensions import db


class RetiredItem(db.Model):
    __tablename__ = "retired_items"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    item_id = db.Column(db.Integer, db.ForeignKey("items.id", ondelete="SET NULL"), nullable=True, index=True)

    title = db.Column(db.String, nullable=False)
    sku = db.Column(db.String, nullable=True)

    ebay_listing_id = db.Column(db.String(100), nullable=True, index=True)
    ebay_url = db.Column(db.String, nullable=True)

    item_thumb = db.Column(db.String, nullable=True)
    item_price = db.Column(db.Float, nullable=True)
    item_cost = db.Column(db.Float, nullable=True)
    supplier = db.Column(db.String, nullable=True, index=True)
    location_code = db.Column(db.String, nullable=True, index=True)

    status = db.Column(db.String(20), default="pending", nullable=False, index=True)
    note = db.Column(db.Text, nullable=True)
    last_error = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    purged_at = db.Column(db.DateTime, nullable=True)

