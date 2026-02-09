from datetime import datetime
from qventory.extensions import db


class ItemCostHistory(db.Model):
    __tablename__ = "item_cost_history"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    item_id = db.Column(db.Integer, db.ForeignKey("items.id"), nullable=False, index=True)

    source = db.Column(db.String(50), nullable=False, default="manual")  # manual, expense, receipt
    previous_cost = db.Column(db.Float, nullable=True)
    new_cost = db.Column(db.Float, nullable=True)
    delta = db.Column(db.Float, nullable=True)
    note = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    item = db.relationship("Item", backref=db.backref("cost_history", lazy='dynamic'))
