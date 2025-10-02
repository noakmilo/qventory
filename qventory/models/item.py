from datetime import datetime
from ..extensions import db

class Item(db.Model):
    __tablename__ = "items"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    title = db.Column(db.String, nullable=False)
    sku = db.Column(db.String, unique=True, nullable=False)
    listing_link = db.Column(db.String, nullable=True)

    # URLs de venta
    web_url = db.Column(db.String, nullable=True)
    ebay_url = db.Column(db.String, nullable=True)
    amazon_url = db.Column(db.String, nullable=True)
    mercari_url = db.Column(db.String, nullable=True)
    vinted_url = db.Column(db.String, nullable=True)
    poshmark_url = db.Column(db.String, nullable=True)
    depop_url = db.Column(db.String, nullable=True)

    # Ubicación
    A = db.Column(db.String, nullable=True)
    B = db.Column(db.String, nullable=True)
    S = db.Column(db.String, nullable=True)
    C = db.Column(db.String, nullable=True)

    location_code = db.Column(db.String, index=True)

    # Nuevos campos
    item_thumb = db.Column(db.String, nullable=True)       # URL de Cloudinary
    supplier = db.Column(db.String, nullable=True)         # Nombre de la tienda
    item_cost = db.Column(db.Float, nullable=True)         # Costo en $
    item_price = db.Column(db.Float, nullable=True)        # Precio en $
    listing_date = db.Column(db.Date, nullable=True)       # Fecha de publicación

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
