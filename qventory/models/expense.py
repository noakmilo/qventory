from datetime import datetime
from ..extensions import db

class Expense(db.Model):
    """
    Business Expenses - Gastos operativos del negocio
    Permite tracking de gastos recurrentes y one-time
    """
    __tablename__ = "expenses"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    # Información del gasto
    description = db.Column(db.String(255), nullable=False)  # "Cajas de envío", "Renta garaje"
    amount = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(100), nullable=True, index=True)  # "Supplies", "Rent", "Transportation", etc.

    # Fecha
    expense_date = db.Column(db.Date, nullable=False, index=True)  # Fecha del gasto

    # Recurrencia (opcional)
    is_recurring = db.Column(db.Boolean, default=False, index=True)
    recurring_frequency = db.Column(db.String(20), nullable=True)  # "monthly", "yearly", "weekly"
    recurring_day = db.Column(db.Integer, nullable=True)  # Día del mes (1-31) para monthly
    recurring_until = db.Column(db.Date, nullable=True)  # Fecha final de recurrencia (null = indefinido)

    # Optional link to inventory item
    item_id = db.Column(db.Integer, db.ForeignKey("items.id"), nullable=True, index=True)
    item_cost_applied = db.Column(db.Boolean, default=False, index=True)
    item_cost_applied_amount = db.Column(db.Float, nullable=True)
    item_cost_applied_at = db.Column(db.DateTime, nullable=True)

    # Metadata
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relación
    user = db.relationship("User", backref="expenses")
    item = db.relationship("Item", backref="expenses")

    def __repr__(self):
        return f"<Expense {self.description} - ${self.amount}>"

    @property
    def is_active_recurring(self):
        """Check if recurring expense is still active"""
        if not self.is_recurring:
            return False
        if self.recurring_until and self.recurring_until < datetime.utcnow().date():
            return False
        return True


# Categorías predefinidas (para UI)
EXPENSE_CATEGORIES = [
    "Supplies",           # Cajas, papel, cinta, etiquetas
    "Rent/Storage",       # Renta de garaje, storage unit
    "Transportation",     # Uber, gasolina, estacionamiento
    "Utilities",          # Internet, electricidad, agua
    "Tools/Equipment",    # Impresora, báscula, shelving
    "Software",           # Apps, tools (excluyendo eBay store)
    "Services",           # Contador, abogado, freelancers
    "Marketing",          # Ads, promociones
    "Other"               # Todo lo demás
]
