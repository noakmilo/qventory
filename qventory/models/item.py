from datetime import datetime
from sqlalchemy import UniqueConstraint
from ..extensions import db

class Item(db.Model):
    __tablename__ = "items"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "ebay_listing_id",
            name="uq_items_user_ebay_listing",
        ),
    )
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    title = db.Column(db.String, nullable=False)
    sku = db.Column(db.String, unique=True, nullable=False)  # Qventory's unique SKU (20251029-A3B4)
    description = db.Column(db.Text, nullable=True)  # Descripción detallada

    # Identificadores externos
    upc = db.Column(db.String, nullable=True, index=True)  # Código UPC/EAN
    listing_link = db.Column(db.String, nullable=True)

    # URLs de venta (deprecated - migrar a tabla listings)
    web_url = db.Column(db.String, nullable=True)
    ebay_url = db.Column(db.String, nullable=True)
    amazon_url = db.Column(db.String, nullable=True)
    mercari_url = db.Column(db.String, nullable=True)
    vinted_url = db.Column(db.String, nullable=True)
    poshmark_url = db.Column(db.String, nullable=True)
    depop_url = db.Column(db.String, nullable=True)
    whatnot_url = db.Column(db.String, nullable=True)  # Nuevo

    # Ubicación
    A = db.Column(db.String, nullable=True)
    B = db.Column(db.String, nullable=True)
    S = db.Column(db.String, nullable=True)
    C = db.Column(db.String, nullable=True)
    location_code = db.Column(db.String, index=True)

    # Imágenes
    item_thumb = db.Column(db.String, nullable=True)  # URL de Cloudinary (principal)
    image_urls = db.Column(db.JSON, nullable=True)  # Array de URLs adicionales

    # Pricing y costo
    supplier = db.Column(db.String, nullable=True, index=True)  # Nombre de la tienda
    item_cost = db.Column(db.Float, nullable=True)  # Costo en $
    item_price = db.Column(db.Float, nullable=True)  # Precio sugerido $

    # Inventory management
    quantity = db.Column(db.Integer, default=1, nullable=False)  # Cantidad en stock
    low_stock_threshold = db.Column(db.Integer, default=1)  # Alerta de bajo stock
    is_active = db.Column(db.Boolean, default=True, index=True)  # Item activo o archivado
    inactive_by_user = db.Column(db.Boolean, default=False, nullable=False, index=True)  # Hidden by user

    # Categorización
    category = db.Column(db.String, nullable=True, index=True)
    tags = db.Column(db.JSON, nullable=True)  # Array de tags

    # Fechas
    listing_date = db.Column(db.Date, nullable=True)  # Fecha de publicación
    purchased_at = db.Column(db.Date, nullable=True)  # Fecha de compra al supplier

    # eBay Sync fields
    ebay_listing_id = db.Column(db.String(100), nullable=True, index=True)  # eBay Listing ID (active)
    ebay_sku = db.Column(db.String(100), nullable=True)  # Custom SKU from eBay
    synced_from_ebay = db.Column(db.Boolean, default=False)  # Imported from eBay
    last_ebay_sync = db.Column(db.DateTime, nullable=True)  # Last sync with eBay
    previous_item_id = db.Column(db.Integer, db.ForeignKey("items.id"), nullable=True, index=True)

    # Sold tracking (soft delete)
    sold_at = db.Column(db.DateTime, nullable=True, index=True)  # When item was sold
    sold_price = db.Column(db.Float, nullable=True)  # Price it sold for

    # Metadata
    notes = db.Column(db.Text, nullable=True)  # Notas internas
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def is_low_stock(self):
        """Check if item is below threshold"""
        return self.quantity <= self.low_stock_threshold

    @property
    def total_sold(self):
        """Total quantity sold from this item"""
        from .sale import Sale
        result = db.session.query(db.func.count(Sale.id)).filter(
            Sale.item_id == self.id,
            Sale.status.in_(['completed', 'shipped', 'paid'])
        ).scalar()
        return result or 0

    @property
    def total_revenue(self):
        """Total revenue from sales of this item"""
        from .sale import Sale
        result = db.session.query(db.func.sum(Sale.sold_price)).filter(
            Sale.item_id == self.id,
            Sale.status.in_(['completed', 'shipped', 'paid'])
        ).scalar()
        return result or 0.0

    @property
    def total_profit(self):
        """Total net profit from sales of this item"""
        from .sale import Sale
        result = db.session.query(db.func.sum(Sale.net_profit)).filter(
            Sale.item_id == self.id,
            Sale.status.in_(['completed', 'shipped', 'paid'])
        ).scalar()
        return result or 0.0
