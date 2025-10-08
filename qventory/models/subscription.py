from datetime import datetime, timedelta
from ..extensions import db

class Subscription(db.Model):
    """
    Tabla para gestión de suscripciones (Free vs Premium)
    """
    __tablename__ = "subscriptions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True, index=True)

    # Plan
    plan = db.Column(db.String(50), nullable=False, default='free', index=True)  # free, early_adopter, premium, pro
    status = db.Column(db.String(50), nullable=False, default='active', index=True)  # active, cancelled, expired, suspended

    # Fechas
    started_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    current_period_start = db.Column(db.DateTime, nullable=True)
    current_period_end = db.Column(db.DateTime, nullable=True)
    cancelled_at = db.Column(db.DateTime, nullable=True)
    ended_at = db.Column(db.DateTime, nullable=True)

    # Stripe/Payment info (para futuro)
    stripe_customer_id = db.Column(db.String(255), nullable=True, index=True)
    stripe_subscription_id = db.Column(db.String(255), nullable=True, index=True)

    # Trial
    trial_ends_at = db.Column(db.DateTime, nullable=True)
    on_trial = db.Column(db.Boolean, default=False)

    # Metadata
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relación
    user = db.relationship("User", backref=db.backref("subscription", uselist=False))

    @property
    def is_active(self):
        """Check if subscription is currently active"""
        if self.status != 'active':
            return False

        if self.current_period_end:
            return datetime.utcnow() < self.current_period_end

        return True

    @property
    def is_premium(self):
        """Check if user has premium features"""
        return self.is_active and self.plan in ['early_adopter', 'premium', 'pro']

    @property
    def days_until_renewal(self):
        """Days until subscription renews or expires"""
        if not self.current_period_end:
            return None
        delta = self.current_period_end - datetime.utcnow()
        return max(0, delta.days)

    def upgrade_to_pro(self):
        """Upgrade to pro plan"""
        self.plan = 'pro'
        self.status = 'active'
        self.current_period_start = datetime.utcnow()
        self.current_period_end = datetime.utcnow() + timedelta(days=30)
        self.updated_at = datetime.utcnow()

    def downgrade_to_free(self):
        """Downgrade to free plan"""
        self.plan = 'free'
        self.status = 'active'
        self.current_period_end = None
        self.updated_at = datetime.utcnow()

    def cancel(self):
        """Cancel subscription (stays active until period end)"""
        self.cancelled_at = datetime.utcnow()
        self.status = 'cancelled'
        self.updated_at = datetime.utcnow()


class PlanLimit(db.Model):
    """
    Límites por plan (free vs premium)
    """
    __tablename__ = "plan_limits"

    id = db.Column(db.Integer, primary_key=True)
    plan = db.Column(db.String(50), nullable=False, unique=True, index=True)  # free, early_adopter, premium, pro

    # Límites
    max_items = db.Column(db.Integer, nullable=True)  # None = unlimited
    max_images_per_item = db.Column(db.Integer, default=1)
    max_marketplace_integrations = db.Column(db.Integer, default=0)  # APIs conectadas

    # Features
    can_use_ai_research = db.Column(db.Boolean, default=False)
    can_bulk_operations = db.Column(db.Boolean, default=False)
    can_export_csv = db.Column(db.Boolean, default=True)
    can_import_csv = db.Column(db.Boolean, default=True)
    can_use_analytics = db.Column(db.Boolean, default=False)
    can_create_listings = db.Column(db.Boolean, default=False)  # Create listings via API

    # Support
    support_level = db.Column(db.String(50), default='community')  # community, email, priority

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
