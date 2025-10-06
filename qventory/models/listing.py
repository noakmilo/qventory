from datetime import datetime
from ..extensions import db

class Listing(db.Model):
    """
    Tabla para tracking de listings activos en marketplaces
    Vincula un Item con sus listings en diferentes plataformas
    """
    __tablename__ = "listings"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    item_id = db.Column(db.Integer, db.ForeignKey("items.id"), nullable=False, index=True)

    # Marketplace info
    marketplace = db.Column(db.String(50), nullable=False, index=True)  # ebay, mercari, depop, whatnot
    marketplace_listing_id = db.Column(db.String(255), nullable=True, index=True)  # ID del listing en la plataforma
    marketplace_url = db.Column(db.String, nullable=True)  # URL del listing

    # Listing details
    title = db.Column(db.String, nullable=True)
    description = db.Column(db.Text, nullable=True)
    price = db.Column(db.Float, nullable=True)
    quantity = db.Column(db.Integer, default=1)

    # eBay specific fields
    ebay_custom_sku = db.Column(db.String(100), nullable=True)  # Custom SKU synced to eBay (location code)

    # Estado
    status = db.Column(db.String(50), nullable=False, default='draft', index=True)  # draft, active, sold, ended, deleted
    is_synced = db.Column(db.Boolean, default=False, index=True)  # Si está sincronizado con la plataforma

    # Fechas
    listed_at = db.Column(db.DateTime, nullable=True)
    ended_at = db.Column(db.DateTime, nullable=True)
    last_synced_at = db.Column(db.DateTime, nullable=True)

    # Sync info
    sync_error = db.Column(db.Text, nullable=True)

    # Metadata
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    item = db.relationship("Item", backref="listings")

    # Unique constraint: un item solo puede tener un listing activo por marketplace
    __table_args__ = (
        db.Index('idx_item_marketplace_status', 'item_id', 'marketplace', 'status'),
    )
