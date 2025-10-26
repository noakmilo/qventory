"""
Receipt OCR Usage Tracking Model

Tracks AI-powered OCR usage per user to enforce plan limits.
Supports both daily limits (for free plan) and monthly limits (for paid plans).
"""
from datetime import datetime, timedelta
from sqlalchemy import func
from ..extensions import db


class ReceiptUsage(db.Model):
    """Track receipt OCR usage for plan limit enforcement"""
    __tablename__ = "receipt_usage"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    receipt_id = db.Column(db.Integer, db.ForeignKey("receipts.id", ondelete="CASCADE"), nullable=False)

    # When was OCR performed
    processed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    # What plan was user on when OCR was performed
    plan_at_time = db.Column(db.String(50), nullable=False)

    # OCR provider used
    ocr_provider = db.Column(db.String(50), default='openai_vision')

    # Optional: cost tracking for analytics
    estimated_cost = db.Column(db.Numeric(10, 4), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    user = db.relationship("User", backref=db.backref("receipt_usage", passive_deletes=True), passive_deletes=True)
    receipt = db.relationship("Receipt", backref=db.backref("usage_record", uselist=False, passive_deletes=True), uselist=False, passive_deletes=True)

    @staticmethod
    def get_usage_today(user_id: int) -> int:
        """Get count of receipts processed today"""
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

        count = db.session.query(func.count(ReceiptUsage.id)).filter(
            ReceiptUsage.user_id == user_id,
            ReceiptUsage.processed_at >= today_start
        ).scalar()

        return count or 0

    @staticmethod
    def get_usage_this_month(user_id: int) -> int:
        """Get count of receipts processed this month"""
        month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        count = db.session.query(func.count(ReceiptUsage.id)).filter(
            ReceiptUsage.user_id == user_id,
            ReceiptUsage.processed_at >= month_start
        ).scalar()

        return count or 0

    @staticmethod
    def can_process_receipt(user, plan_limits) -> tuple[bool, str, int, int]:
        """
        Check if user can process another receipt with AI OCR

        Returns:
            (can_process, message, used, limit)
            - can_process: bool - whether user can process receipt
            - message: str - explanation message
            - used: int - how many used so far
            - limit: int - the limit (or None for unlimited)
        """
        # God mode bypasses all limits
        if user.is_god_mode:
            return True, "God mode - unlimited", 0, None

        # Check daily limit (for free plan)
        if plan_limits.max_receipt_ocr_per_day is not None:
            used_today = ReceiptUsage.get_usage_today(user.id)

            if used_today >= plan_limits.max_receipt_ocr_per_day:
                return (
                    False,
                    f"Daily limit reached. You've used {used_today}/{plan_limits.max_receipt_ocr_per_day} AI OCR receipts today. Resets at midnight.",
                    used_today,
                    plan_limits.max_receipt_ocr_per_day
                )

            return (
                True,
                f"OK - {used_today}/{plan_limits.max_receipt_ocr_per_day} used today",
                used_today,
                plan_limits.max_receipt_ocr_per_day
            )

        # Check monthly limit (for paid plans)
        if plan_limits.max_receipt_ocr_per_month is not None:
            used_this_month = ReceiptUsage.get_usage_this_month(user.id)

            if used_this_month >= plan_limits.max_receipt_ocr_per_month:
                return (
                    False,
                    f"Monthly limit reached. You've used {used_this_month}/{plan_limits.max_receipt_ocr_per_month} AI OCR receipts this month. Upgrade for more.",
                    used_this_month,
                    plan_limits.max_receipt_ocr_per_month
                )

            return (
                True,
                f"OK - {used_this_month}/{plan_limits.max_receipt_ocr_per_month} used this month",
                used_this_month,
                plan_limits.max_receipt_ocr_per_month
            )

        # No limits set - unlimited
        return True, "Unlimited", 0, None

    @staticmethod
    def record_usage(user_id: int, receipt_id: int, plan: str, provider: str = 'openai_vision', cost: float = None):
        """Record that a receipt was processed with AI OCR"""
        usage = ReceiptUsage(
            user_id=user_id,
            receipt_id=receipt_id,
            plan_at_time=plan,
            ocr_provider=provider,
            estimated_cost=cost
        )
        db.session.add(usage)
        db.session.commit()
        return usage

    def __repr__(self):
        return f"<ReceiptUsage user={self.user_id} receipt={self.receipt_id} at={self.processed_at}>"
