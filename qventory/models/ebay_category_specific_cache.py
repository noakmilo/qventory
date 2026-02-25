from datetime import datetime
from ..extensions import db


class EbayCategorySpecificCache(db.Model):
    __tablename__ = "ebay_category_specific_cache"

    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.String(64), nullable=False, index=True)
    marketplace_id = db.Column(db.String(32), nullable=False, default="EBAY_US", index=True)

    required_fields_json = db.Column(db.JSON, nullable=True)
    optional_fields_json = db.Column(db.JSON, nullable=True)
    fetched_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=True)
    source_version = db.Column(db.String(64), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("category_id", "marketplace_id", name="uq_ebay_category_specific_cache"),
    )

    def to_dict(self):
        return {
            "category_id": self.category_id,
            "marketplace_id": self.marketplace_id,
            "required_fields": self.required_fields_json or [],
            "optional_fields": self.optional_fields_json or [],
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "source_version": self.source_version,
        }
