from datetime import datetime
from ..extensions import db


class EbayListingDraft(db.Model):
    __tablename__ = "ebay_listing_drafts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    status = db.Column(db.String(20), nullable=False, default="DRAFT", index=True)
    title = db.Column(db.String(80), nullable=True)
    description_html = db.Column(db.Text, nullable=True)
    description_html_sanitized = db.Column(db.Text, nullable=True)
    description_text = db.Column(db.Text, nullable=True)

    category_id = db.Column(db.String(64), nullable=True, index=True)
    item_specifics_json = db.Column(db.JSON, nullable=True)

    condition_id = db.Column(db.String(32), nullable=True)
    condition_label = db.Column(db.String(64), nullable=True)

    sku = db.Column(db.String(64), nullable=True, index=True)
    quantity = db.Column(db.Integer, nullable=True)
    price = db.Column(db.Numeric(10, 2), nullable=True)
    currency = db.Column(db.String(8), nullable=True, default="USD")

    location_postal_code = db.Column(db.String(16), nullable=True)
    location_city = db.Column(db.String(80), nullable=True)
    location_state = db.Column(db.String(32), nullable=True)
    location_country = db.Column(db.String(2), nullable=True, default="US")
    merchant_location_key = db.Column(db.String(64), nullable=True)

    fulfillment_policy_id = db.Column(db.String(64), nullable=True)
    payment_policy_id = db.Column(db.String(64), nullable=True)
    return_policy_id = db.Column(db.String(64), nullable=True)

    images_json = db.Column(db.JSON, nullable=True)

    last_error = db.Column(db.Text, nullable=True)
    ebay_listing_id = db.Column(db.String(100), nullable=True, index=True)
    published_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship("User", backref=db.backref("ebay_listing_drafts", lazy="dynamic"))

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "status": self.status,
            "title": self.title,
            "description_html": self.description_html,
            "description_html_sanitized": self.description_html_sanitized,
            "description_text": self.description_text,
            "category_id": self.category_id,
            "item_specifics": self.item_specifics_json or {},
            "condition_id": self.condition_id,
            "condition_label": self.condition_label,
            "sku": self.sku,
            "quantity": self.quantity,
            "price": float(self.price) if self.price is not None else None,
            "currency": self.currency,
            "location": {
                "postal_code": self.location_postal_code,
                "city": self.location_city,
                "state": self.location_state,
                "country": self.location_country,
                "merchant_location_key": self.merchant_location_key,
            },
            "policy_ids": {
                "fulfillment": self.fulfillment_policy_id,
                "payment": self.payment_policy_id,
                "return": self.return_policy_id,
            },
            "images": self.images_json or [],
            "last_error": self.last_error,
            "ebay_listing_id": self.ebay_listing_id,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
