from datetime import datetime

from qventory.extensions import db


class EbayFeedback(db.Model):
    __tablename__ = "ebay_feedback"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    feedback_id = db.Column(db.String(64), nullable=False)
    comment_type = db.Column(db.String(20))
    comment_text = db.Column(db.Text)
    comment_time = db.Column(db.DateTime)
    commenting_user = db.Column(db.String(80))
    role = db.Column(db.String(40))
    item_id = db.Column(db.String(40))
    transaction_id = db.Column(db.String(40))
    order_line_item_id = db.Column(db.String(80))
    item_title = db.Column(db.String(255))
    response_text = db.Column(db.Text)
    response_type = db.Column(db.String(20))
    response_time = db.Column(db.DateTime)
    responded = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("user_id", "feedback_id", name="uq_ebay_feedback_user_feedback"),
        db.Index("idx_ebay_feedback_user_time", "user_id", "comment_time"),
    )
