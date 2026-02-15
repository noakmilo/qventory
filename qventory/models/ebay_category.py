from datetime import datetime
from ..extensions import db


class EbayCategory(db.Model):
    __tablename__ = "ebay_categories"

    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.String(64), nullable=False, unique=True, index=True)
    name = db.Column(db.String(255), nullable=False, index=True)
    parent_id = db.Column(db.String(64), nullable=True, index=True)
    full_path = db.Column(db.String(1000), nullable=False, index=True)
    level = db.Column(db.Integer, default=0)
    is_leaf = db.Column(db.Boolean, default=False)
    tree_id = db.Column(db.String(64), nullable=True)
    tree_version = db.Column(db.String(64), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "category_id": self.category_id,
            "name": self.name,
            "parent_id": self.parent_id,
            "full_path": self.full_path,
            "level": self.level,
            "is_leaf": self.is_leaf,
        }
