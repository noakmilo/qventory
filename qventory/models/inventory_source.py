from datetime import datetime

from ..extensions import db


class InventorySource(db.Model):
    __tablename__ = "inventory_sources"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    image_url = db.Column(db.String(1000), nullable=True)
    link_url = db.Column(db.String(1000), nullable=False)
    allowed_roles = db.Column(db.JSON, nullable=False, default=list)
    is_active = db.Column(db.Boolean, nullable=False, default=False, index=True)
    display_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def allows_role(self, role: str) -> bool:
        roles = self.allowed_roles or []
        return role in roles
