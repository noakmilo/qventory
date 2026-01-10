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
    tax_collected = db.Column(db.Float, nullable=True, default=0)  # Impuestos cobrados al comprador
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
    delivered_at = db.Column(db.DateTime, nullable=True)  # Fecha de entrega

    # Tracking
    tracking_number = db.Column(db.String(255), nullable=True)
    buyer_username = db.Column(db.String(255), nullable=True)
    carrier = db.Column(db.String(100), nullable=True)  # USPS, FedEx, UPS, etc

    # Estado
    status = db.Column(db.String(50), nullable=False, default='pending', index=True)  # pending, paid, shipped, completed, cancelled, refunded, returned

    # Return/Refund tracking
    return_reason = db.Column(db.String(255), nullable=True)  # Reason for return
    returned_at = db.Column(db.DateTime, nullable=True)  # Date item was returned
    refund_amount = db.Column(db.Float, nullable=True)  # Partial or full refund amount
    refund_reason = db.Column(db.String(255), nullable=True)  # Reason for refund

    # eBay specific tracking
    ebay_transaction_id = db.Column(db.String(100), nullable=True, index=True)  # eBay transaction ID
    ebay_buyer_username = db.Column(db.String(100), nullable=True)  # eBay buyer username

    # Metadata
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    item = db.relationship("Item", backref="sales")

    def calculate_profit(self):
        """
        Calcula gross y net profit

        Gross Profit = Sold Price - Item Cost
        Net Profit = Sold Price - Item Cost - Fees - Shipping + Shipping Charged - Liberis Fee

        Si no hay item_cost:
        - gross_profit = None
        - net_profit = sold_price - fees (muestra pérdida/ganancia sin conocer costo)
        """
        # Calculate gross profit only if we know item cost
        if self.item_cost is not None:
            self.gross_profit = self.sold_price - self.item_cost
        else:
            self.gross_profit = None

        # Calculate Liberis fee if applicable
        liberis_fee = self.get_liberis_fee()

        # Calculate total fees (including Liberis)
        total_fees = (
            (self.marketplace_fee or 0) +
            (self.payment_processing_fee or 0) +
            (self.shipping_cost or 0) +
            (self.other_fees or 0) +
            liberis_fee -
            (self.shipping_charged or 0)
        )

        # Calculate net profit
        # If we have item_cost, use gross_profit - fees
        # If we don't have item_cost, show sold_price - fees (partial profit)
        if self.gross_profit is not None:
            self.net_profit = self.gross_profit - total_fees
        else:
            # Even without item_cost, show what's left after fees
            # This gives the seller visibility of actual payout
            self.net_profit = self.sold_price - total_fees

    def get_liberis_fee(self):
        """
        Calculate Liberis fee for this sale if applicable

        Returns:
            float: Liberis fee amount (0 if no active loan or sale is before loan start date)
        """
        from qventory.models.liberis_loan import LiberisLoan
        from datetime import datetime

        # Get active loan for user
        loan = LiberisLoan.get_active_loan(self.user_id)

        if not loan:
            return 0

        # Only apply fee if sale is after loan start date
        if not self.sold_at:
            return 0

        sale_date = self.sold_at.date()
        if sale_date < loan.start_date:
            return 0

        # Calculate fee
        return loan.calculate_fee_for_sale(self.sold_price)
