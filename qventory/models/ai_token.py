"""
AI Token Management
Handles daily token limits for AI Research based on user roles
"""
from datetime import datetime, timedelta
from qventory import db


class AITokenConfig(db.Model):
    """Configuration for AI tokens per role"""
    __tablename__ = 'ai_token_configs'

    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(20), unique=True, nullable=False)  # free, premium, pro, god
    daily_tokens = db.Column(db.Integer, nullable=False)
    display_name = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'role': self.role,
            'daily_tokens': self.daily_tokens,
            'display_name': self.display_name,
            'description': self.description
        }

    @staticmethod
    def get_token_limit(role):
        """Get daily token limit for a role"""
        config = AITokenConfig.query.filter_by(role=role).first()
        if config:
            return config.daily_tokens

        # Defaults if not configured
        defaults = {
            'free': 3,
            'premium': 5,
            'pro': 10,
            'god': 999999
        }
        return defaults.get(role, 0)

    @staticmethod
    def initialize_defaults():
        """Initialize default token configs"""
        defaults = [
            {'role': 'free', 'daily_tokens': 3, 'display_name': 'Free',
             'description': '3 AI Research reports per day'},
            {'role': 'premium', 'daily_tokens': 5, 'display_name': 'Premium',
             'description': '5 AI Research reports per day'},
            {'role': 'pro', 'daily_tokens': 10, 'display_name': 'Pro',
             'description': '10 AI Research reports per day'},
            {'role': 'god', 'daily_tokens': 999999, 'display_name': 'God Mode',
             'description': 'Unlimited AI Research reports'}
        ]

        for config_data in defaults:
            existing = AITokenConfig.query.filter_by(role=config_data['role']).first()
            if not existing:
                config = AITokenConfig(**config_data)
                db.session.add(config)

        db.session.commit()


class AITokenUsage(db.Model):
    """Track daily AI token usage per user"""
    __tablename__ = 'ai_token_usage'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    date = db.Column(db.Date, nullable=False, index=True)
    tokens_used = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = db.relationship('User', backref='token_usage')

    # Unique constraint: one record per user per day
    __table_args__ = (
        db.UniqueConstraint('user_id', 'date', name='unique_user_date'),
    )

    @staticmethod
    def get_today_usage(user_id):
        """Get today's token usage for a user"""
        today = datetime.utcnow().date()
        usage = AITokenUsage.query.filter_by(user_id=user_id, date=today).first()

        if not usage:
            usage = AITokenUsage(user_id=user_id, date=today, tokens_used=0)
            db.session.add(usage)
            db.session.commit()

        return usage

    @staticmethod
    def can_use_token(user):
        """Check if user has tokens available today"""
        # God mode has unlimited tokens
        if user.role == 'god':
            return True, 999999

        today_usage = AITokenUsage.get_today_usage(user.id)
        daily_limit = AITokenConfig.get_token_limit(user.role)
        tokens_remaining = daily_limit - today_usage.tokens_used

        return tokens_remaining > 0, tokens_remaining

    @staticmethod
    def consume_token(user_id):
        """Consume one token for a user"""
        today_usage = AITokenUsage.get_today_usage(user_id)
        today_usage.tokens_used += 1
        db.session.commit()
        return today_usage.tokens_used

    @staticmethod
    def get_user_stats(user):
        """Get token stats for a user"""
        today_usage = AITokenUsage.get_today_usage(user.id)
        daily_limit = AITokenConfig.get_token_limit(user.role)

        return {
            'used_today': today_usage.tokens_used,
            'daily_limit': daily_limit,
            'remaining': max(0, daily_limit - today_usage.tokens_used),
            'role': user.role,
            'unlimited': user.role == 'god'
        }

    @staticmethod
    def cleanup_old_records(days=30):
        """Delete token usage records older than N days"""
        cutoff_date = datetime.utcnow().date() - timedelta(days=days)
        deleted = AITokenUsage.query.filter(AITokenUsage.date < cutoff_date).delete()
        db.session.commit()
        return deleted
