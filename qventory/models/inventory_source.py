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


class InventorySourceReaction(db.Model):
    __tablename__ = "inventory_source_reactions"

    id = db.Column(db.Integer, primary_key=True)
    source_id = db.Column(db.Integer, db.ForeignKey("inventory_sources.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    reaction = db.Column(db.String(10), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    source = db.relationship("InventorySource", backref=db.backref("reactions", cascade="all, delete-orphan", lazy="dynamic"))
    user = db.relationship("User", backref=db.backref("inventory_source_reactions", cascade="all, delete-orphan", lazy="dynamic"))

    __table_args__ = (
        db.UniqueConstraint("source_id", "user_id", name="uq_inventory_source_reactions_source_user"),
    )


class InventorySourceSuggestion(db.Model):
    __tablename__ = "inventory_source_suggestions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    link_url = db.Column(db.String(1000), nullable=False)
    is_archived = db.Column(db.Boolean, nullable=False, default=False, index=True)
    archived_at = db.Column(db.DateTime, nullable=True)
    archived_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", foreign_keys=[user_id], backref=db.backref("inventory_source_suggestions", cascade="all, delete-orphan", lazy="dynamic"))
    archived_by = db.relationship("User", foreign_keys=[archived_by_id])


class ThriftRadarSavedSearch(db.Model):
    __tablename__ = "thrift_radar_saved_searches"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    zip_code = db.Column(db.String(10), nullable=False)
    keywords = db.Column(db.JSON, nullable=False, default=list)
    results = db.Column(db.JSON, nullable=True)
    is_archived = db.Column(db.Boolean, nullable=False, default=False, index=True)
    archived_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship("User", backref=db.backref("thrift_radar_saved_searches", cascade="all, delete-orphan", lazy="dynamic"))

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "zip_code": self.zip_code,
            "keywords": self.keywords or [],
            "results": self.results or [],
            "is_archived": self.is_archived,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
