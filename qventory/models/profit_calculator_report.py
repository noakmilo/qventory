from datetime import datetime
from ..extensions import db


class ProfitCalculatorReport(db.Model):
    __tablename__ = "profit_calculator_reports"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    marketplace = db.Column(db.String(20), nullable=False, index=True)
    item_name = db.Column(db.String(500), nullable=True)

    category_id = db.Column(db.String(64), nullable=True)
    category_path = db.Column(db.String(1000), nullable=True)

    buy_price = db.Column(db.Float, nullable=False)
    resale_price = db.Column(db.Float, nullable=False)
    shipping_cost = db.Column(db.Float, default=0.0)

    has_store = db.Column(db.Boolean, default=False)
    top_rated = db.Column(db.Boolean, default=False)
    include_fixed_fee = db.Column(db.Boolean, default=False)
    ads_fee_rate = db.Column(db.Float, default=0.0)

    fee_breakdown = db.Column(db.JSON)
    total_fees = db.Column(db.Float, default=0.0)
    net_sale = db.Column(db.Float, default=0.0)
    profit = db.Column(db.Float, default=0.0)
    roi = db.Column(db.Float, default=0.0)
    markup = db.Column(db.Float, default=0.0)
    breakeven = db.Column(db.Float, default=0.0)
    output_text = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    user = db.relationship("User", backref="profit_calculator_reports")

    def to_dict(self):
        return {
            "id": self.id,
            "marketplace": self.marketplace,
            "item_name": self.item_name,
            "category_id": self.category_id,
            "category_path": self.category_path,
            "buy_price": self.buy_price,
            "resale_price": self.resale_price,
            "shipping_cost": self.shipping_cost,
            "has_store": self.has_store,
            "top_rated": self.top_rated,
            "include_fixed_fee": self.include_fixed_fee,
            "ads_fee_rate": self.ads_fee_rate,
            "fee_breakdown": self.fee_breakdown,
            "total_fees": self.total_fees,
            "net_sale": self.net_sale,
            "profit": self.profit,
            "roi": self.roi,
            "markup": self.markup,
            "breakeven": self.breakeven,
            "output_text": self.output_text,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
