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
    zip_code = db.Column(db.String(10), nullable=True)
    search_mode = db.Column(db.String(20), nullable=False, default="zip", index=True)
    city = db.Column(db.String(120), nullable=True)
    state = db.Column(db.String(80), nullable=True)
    center_lat = db.Column(db.Float, nullable=True)
    center_lng = db.Column(db.Float, nullable=True)
    radius_meters = db.Column(db.Integer, nullable=False, default=40233)
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
            "search_mode": self.search_mode or "zip",
            "city": self.city,
            "state": self.state,
            "center": (
                {"lat": self.center_lat, "lng": self.center_lng}
                if self.center_lat is not None and self.center_lng is not None
                else None
            ),
            "radius_meters": self.radius_meters,
            "keywords": self.keywords or [],
            "results": self.results or [],
            "is_archived": self.is_archived,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ThriftRadarKeyword(db.Model):
    __tablename__ = "thrift_radar_keywords"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(80), nullable=False, unique=True, index=True)
    label = db.Column(db.String(120), nullable=False)
    keywords = db.Column(db.JSON, nullable=False, default=list)
    match_type = db.Column(db.String(12), nullable=False, default="any")
    icon_url = db.Column(db.String(1000), nullable=True)
    fallback_icon = db.Column(db.String(80), nullable=True)
    color = db.Column(db.String(20), nullable=False, default="#22c55e")
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    display_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_option(self):
        return {
            "id": self.id,
            "slug": self.slug,
            "label": self.label,
            "keywords": self.keywords or [],
            "match_type": self.match_type or "any",
            "icon_url": self.icon_url,
            "icon": self.fallback_icon or "fa-location-dot",
            "color": self.color or "#64748b",
            "is_active": bool(self.is_active),
            "display_order": self.display_order,
        }


class ThriftRadarSavedRoute(db.Model):
    __tablename__ = "thrift_radar_saved_routes"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    saved_search_id = db.Column(db.Integer, db.ForeignKey("thrift_radar_saved_searches.id", ondelete="SET NULL"), nullable=True, index=True)
    title = db.Column(db.String(200), nullable=False)
    mode = db.Column(db.String(20), nullable=False, default="driving")
    origin = db.Column(db.JSON, nullable=True)
    stops = db.Column(db.JSON, nullable=False, default=list)
    route_data = db.Column(db.JSON, nullable=True)
    is_archived = db.Column(db.Boolean, nullable=False, default=False, index=True)
    archived_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship("User", backref=db.backref("thrift_radar_saved_routes", cascade="all, delete-orphan", lazy="dynamic"))
    saved_search = db.relationship("ThriftRadarSavedSearch")

    def to_dict(self):
        return {
            "id": self.id,
            "saved_search_id": self.saved_search_id,
            "title": self.title,
            "mode": self.mode,
            "origin": self.origin or {},
            "stops": self.stops or [],
            "route_data": self.route_data or {},
            "is_archived": self.is_archived,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ThriftRadarLog(db.Model):
    __tablename__ = "thrift_radar_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    saved_search_id = db.Column(db.Integer, db.ForeignKey("thrift_radar_saved_searches.id", ondelete="SET NULL"), nullable=True, index=True)
    event = db.Column(db.String(50), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default="success", index=True)
    zip_code = db.Column(db.String(10), nullable=True, index=True)
    keywords = db.Column(db.JSON, nullable=True)
    result_count = db.Column(db.Integer, nullable=True)
    duration_ms = db.Column(db.Integer, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    metadata_json = db.Column(db.JSON, nullable=True)
    ip_address = db.Column(db.String(64), nullable=True)
    user_agent = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    user = db.relationship("User", backref=db.backref("thrift_radar_logs", cascade="all, delete-orphan", lazy="dynamic"))
    saved_search = db.relationship("ThriftRadarSavedSearch")
