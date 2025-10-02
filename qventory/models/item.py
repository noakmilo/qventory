from datetime import datetime
from ..extensions import db

class Item(db.Model):
    __tablename__ = "items"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    title = db.Column(db.String, nullable=False)
    sku = db.Column(db.String, unique=True, nullable=False)
    listing_link = db.Column(db.String, nullable=True)

    web_url = db.Column(db.String, nullable=True)
    ebay_url = db.Column(db.String, nullable=True)
    amazon_url = db.Column(db.String, nullable=True)
    mercari_url = db.Column(db.String, nullable=True)
    vinted_url = db.Column(db.String, nullable=True)
    poshmark_url = db.Column(db.String, nullable=True)
    depop_url = db.Column(db.String, nullable=True)

    A = db.Column(db.String, nullable=True)
    B = db.Column(db.String, nullable=True)
    S = db.Column(db.String, nullable=True)
    C = db.Column(db.String, nullable=True)

    location_code = db.Column(db.String, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
