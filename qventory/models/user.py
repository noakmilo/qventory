from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from ..extensions import db, login_manager

class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default='free', nullable=False)  # free, early_adopter, premium, plus, pro, god, enterprise
    email_verified = db.Column(db.Boolean, default=False, nullable=False)  # Email verification status
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime, nullable=True)  # Last explicit login (username/password)
    last_activity = db.Column(db.DateTime, nullable=True)  # Last activity (any authenticated request)
    monthly_expense_budget = db.Column(db.Numeric(10, 2), nullable=True)  # Monthly budget for expenses

    # opcional: relaciones convenientes
    items = db.relationship("Item", backref="owner", lazy="dynamic", cascade="all, delete-orphan")
    settings = db.relationship("Setting", backref="owner", uselist=False, cascade="all, delete-orphan")
    sales = db.relationship("Sale", backref="seller", lazy="dynamic", cascade="all, delete-orphan")
    listings = db.relationship("Listing", backref="seller", lazy="dynamic", cascade="all, delete-orphan")
    marketplace_credentials = db.relationship("MarketplaceCredential", backref="owner", lazy="dynamic", cascade="all, delete-orphan")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    # ==================== SUBSCRIPTION & PLAN LIMITS ====================

    def get_subscription(self):
        """Get user's subscription (creates free plan if none exists)"""
        from .subscription import Subscription

        # Always query fresh data to avoid caching issues after plan upgrades
        subscription = Subscription.query.filter_by(user_id=self.id).first()

        if subscription:
            return subscription

        # Create free subscription if none exists
        subscription = Subscription(
            user_id=self.id,
            plan='free',
            status='active'
        )
        db.session.add(subscription)
        db.session.commit()
        return subscription

    def get_plan_limits(self):
        """Get plan limits for current subscription"""
        from .subscription import PlanLimit

        subscription = self.get_subscription()
        limits = PlanLimit.query.filter_by(plan=subscription.plan).first()

        if not limits:
            # Return free plan limits as default
            limits = PlanLimit.query.filter_by(plan='free').first()

        return limits

    def can_use_feature(self, feature: str) -> bool:
        """
        Check if user can use a specific feature

        Features:
        - ai_research
        - bulk_operations
        - export_csv
        - import_csv
        - analytics
        - create_listings
        """
        # God mode bypasses all restrictions
        if self.is_god_mode:
            return True

        subscription = self.get_subscription()

        # Check if subscription is active
        if not subscription.is_active:
            return False

        limits = self.get_plan_limits()

        feature_map = {
            'ai_research': limits.can_use_ai_research,
            'bulk_operations': limits.can_bulk_operations,
            'export_csv': limits.can_export_csv,
            'import_csv': limits.can_import_csv,
            'analytics': limits.can_use_analytics,
            'create_listings': limits.can_create_listings,
        }

        return feature_map.get(feature, False)

    def can_add_items(self, count: int = 1) -> bool:
        """Check if user can add more items"""
        # God mode has unlimited items
        if self.is_god_mode:
            return True

        limits = self.get_plan_limits()

        # None means unlimited
        if limits.max_items is None:
            return True

        # Efficient count query - use same optimization as items_remaining()
        from sqlalchemy import text
        result = db.session.execute(
            text("SELECT COUNT(*) FROM items WHERE user_id = :user_id"),
            {"user_id": self.id}
        )
        current_count = result.scalar()
        return (current_count + count) <= limits.max_items

    def can_add_marketplace(self) -> bool:
        """Check if user can connect more marketplaces"""
        # God mode has unlimited marketplace integrations
        if self.is_god_mode:
            return True

        limits = self.get_plan_limits()

        if limits.max_marketplace_integrations == 0:
            return False

        current_count = self.marketplace_credentials.count()
        return current_count < limits.max_marketplace_integrations

    def items_remaining(self) -> int:
        """Get number of items user can still add (None = unlimited)"""
        # God mode has unlimited items
        if self.is_god_mode:
            return None

        limits = self.get_plan_limits()

        if limits.max_items is None:
            return None

        # Efficient count query - only count IDs instead of loading all columns
        # Use text query to avoid ORM overhead and potential circular imports
        from sqlalchemy import text
        result = db.session.execute(
            text("SELECT COUNT(*) FROM items WHERE user_id = :user_id"),
            {"user_id": self.id}
        )
        current_count = result.scalar()
        return max(0, limits.max_items - current_count)

    @property
    def is_premium(self) -> bool:
        """Check if user has premium plan"""
        subscription = self.get_subscription()
        return subscription.is_premium

    @property
    def plan_name(self) -> str:
        """Get current plan name"""
        subscription = self.get_subscription()
        return subscription.plan.capitalize()

    # ==================== AI TOKEN MANAGEMENT ====================

    def get_ai_token_stats(self):
        """Get AI token usage statistics"""
        from .ai_token import AITokenUsage
        return AITokenUsage.get_user_stats(self)

    def can_use_ai_research(self):
        """Check if user has AI research tokens available"""
        from .ai_token import AITokenUsage
        can_use, remaining = AITokenUsage.can_use_token(self)
        return can_use, remaining

    def consume_ai_token(self):
        """Consume one AI research token"""
        from .ai_token import AITokenUsage
        return AITokenUsage.consume_token(self.id)

    @property
    def is_god_mode(self):
        """Check if user has god mode (unlimited access)"""
        return self.role == 'god'

    @property
    def role_display_name(self):
        """Get display name for user's role"""
        names = {
            'free': 'Free',
            'early_adopter': 'Early Adopter',
            'premium': 'Premium',
            'plus': 'Plus',
            'pro': 'Pro',
            'god': 'God Mode',
            'enterprise': 'Enterprise'
        }
        return names.get(self.role, 'Free')

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))
