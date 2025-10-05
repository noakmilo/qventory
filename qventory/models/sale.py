from datetime import datetime
from ..extensions import db

class Sale(db.Model):
    """
    Tabla para tracking de ventas reales
    Registra cada venta con detalles completos para analytics y profit tracking
    """
    __tablename__ = "sales"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    item_id = db.Column(db.Integer, db.ForeignKey("items.id"), nullable=True, index=True)  # Nullable para ventas de items eliminados

    # Información de la venta
    marketplace = db.Column(db.String(50), nullable=False, index=True)  # ebay, mercari, depop, whatnot, etc
    marketplace_order_id = db.Column(db.String(255), nullable=True, index=True)  # ID del pedido en la plataforma

    # Snapshot del item (por si se elimina después)
    item_title = db.Column(db.String, nullable=False)
    item_sku = db.Column(db.String, nullable=True)

    # Precios y costos
    sold_price = db.Column(db.Float, nullable=False)  # Precio de venta
    item_cost = db.Column(db.Float, nullable=True)  # Costo del item (snapshot)

    # Fees y gastos
    marketplace_fee = db.Column(db.Float, nullable=True, default=0)  # Fee de la plataforma
    payment_processing_fee = db.Column(db.Float, nullable=True, default=0)  # Fee de procesamiento (PayPal, Stripe, etc)
    shipping_cost = db.Column(db.Float, nullable=True, default=0)  # Costo real de envío
    shipping_charged = db.Column(db.Float, nullable=True, default=0)  # Lo que cobró al comprador
    other_fees = db.Column(db.Float, nullable=True, default=0)  # Otros fees (promociones, etc)

    # Profit calculado
    gross_profit = db.Column(db.Float, nullable=True)  # sold_price - item_cost
    net_profit = db.Column(db.Float, nullable=True)  # gross_profit - fees - shipping_cost + shipping_charged

    # Fechas
    sold_at = db.Column(db.DateTime, nullable=False, index=True)  # Fecha de venta
    paid_at = db.Column(db.DateTime, nullable=True)  # Fecha de pago recibido
    shipped_at = db.Column(db.DateTime, nullable=True)  # Fecha de envío

    # Tracking
    tracking_number = db.Column(db.String(255), nullable=True)
    buyer_username = db.Column(db.String(255), nullable=True)

    # Estado
    status = db.Column(db.String(50), nullable=False, default='pending', index=True)  # pending, paid, shipped, completed, cancelled, refunded

    # Metadata
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    item = db.relationship("Item", backref="sales")

    def calculate_profit(self):
        """Calcula gross y net profit"""
        if self.item_cost is not None:
            self.gross_profit = self.sold_price - self.item_cost
        else:
            self.gross_profit = None

        if self.gross_profit is not None:
            total_fees = (
                (self.marketplace_fee or 0) +
                (self.payment_processing_fee or 0) +
                (self.shipping_cost or 0) +
                (self.other_fees or 0) -
                (self.shipping_charged or 0)
            )
            self.net_profit = self.gross_profit - total_fees
        else:
            self.net_profit = None
