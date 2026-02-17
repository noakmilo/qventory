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
    role = db.Column(db.String(20), nullable=False)  # free, premium, pro, god
    scenario = db.Column(db.String(40), nullable=False, default='ai_research')
    daily_tokens = db.Column(db.Integer, nullable=False)
    display_name = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'role': self.role,
            'scenario': self.scenario,
            'daily_tokens': self.daily_tokens,
            'display_name': self.display_name,
            'description': self.description
        }

    @staticmethod
    def get_token_limit(role, scenario='ai_research'):
        """Get daily token limit for a role"""
        config = AITokenConfig.query.filter_by(role=role, scenario=scenario).first()
        if config:
            return config.daily_tokens

        # Defaults if not configured
        defaults_ai_research = {
            'free': 3,
            'early_adopter': 10,
            'premium': 5,
            'plus': 15,
            'pro': 10,
            'god': 999999,
            'enterprise': 999999
        }
        defaults_feedback = {
            'free': 3,
            'early_adopter': 3,
            'premium': 5,
            'plus': 10,
            'pro': 20,
            'god': 999999,
            'enterprise': 999999
        }
        defaults = defaults_ai_research if scenario == 'ai_research' else defaults_feedback
        return defaults.get(role, 0)

    @staticmethod
    def initialize_defaults():
        """Initialize default token configs"""
        defaults = [
            # AI Research
            {'role': 'free', 'scenario': 'ai_research', 'daily_tokens': 3, 'display_name': 'Free',
             'description': '3 AI Research reports per day'},
            {'role': 'early_adopter', 'scenario': 'ai_research', 'daily_tokens': 10, 'display_name': 'Early Adopter',
             'description': '10 AI Research reports per day'},
            {'role': 'premium', 'scenario': 'ai_research', 'daily_tokens': 5, 'display_name': 'Premium',
             'description': '5 AI Research reports per day'},
            {'role': 'plus', 'scenario': 'ai_research', 'daily_tokens': 15, 'display_name': 'Plus',
             'description': '15 AI Research reports per day'},
            {'role': 'pro', 'scenario': 'ai_research', 'daily_tokens': 10, 'display_name': 'Pro',
             'description': '10 AI Research reports per day'},
            {'role': 'god', 'scenario': 'ai_research', 'daily_tokens': 999999, 'display_name': 'God Mode',
             'description': 'Unlimited AI Research reports'},
            {'role': 'enterprise', 'scenario': 'ai_research', 'daily_tokens': 999999, 'display_name': 'Enterprise',
             'description': 'Unlimited AI Research reports'},
            # Feedback Manager
            {'role': 'free', 'scenario': 'feedback_manager', 'daily_tokens': 3, 'display_name': 'Free',
             'description': '3 feedback AI replies per day'},
            {'role': 'early_adopter', 'scenario': 'feedback_manager', 'daily_tokens': 3, 'display_name': 'Early Adopter',
             'description': '3 feedback AI replies per day'},
            {'role': 'premium', 'scenario': 'feedback_manager', 'daily_tokens': 5, 'display_name': 'Premium',
             'description': '5 feedback AI replies per day'},
            {'role': 'plus', 'scenario': 'feedback_manager', 'daily_tokens': 10, 'display_name': 'Plus',
             'description': '10 feedback AI replies per day'},
            {'role': 'pro', 'scenario': 'feedback_manager', 'daily_tokens': 20, 'display_name': 'Pro',
             'description': '20 feedback AI replies per day'},
            {'role': 'god', 'scenario': 'feedback_manager', 'daily_tokens': 999999, 'display_name': 'God Mode',
             'description': 'Unlimited feedback AI replies'},
            {'role': 'enterprise', 'scenario': 'feedback_manager', 'daily_tokens': 999999, 'display_name': 'Enterprise',
             'description': 'Unlimited feedback AI replies'}
        ]

        for config_data in defaults:
            existing = AITokenConfig.query.filter_by(
                role=config_data['role'],
                scenario=config_data.get('scenario', 'ai_research')
            ).first()
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
    scenario = db.Column(db.String(40), nullable=False, default='ai_research', index=True)
    tokens_used = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = db.relationship('User', backref='token_usage')

    # Unique constraint: one record per user per day
    __table_args__ = (
        db.UniqueConstraint('user_id', 'date', 'scenario', name='unique_user_date_scenario'),
    )

    @staticmethod
    def get_today_usage(user_id, scenario='ai_research'):
        """Get today's token usage for a user"""
        today = datetime.utcnow().date()
        usage = AITokenUsage.query.filter_by(
            user_id=user_id,
            date=today,
            scenario=scenario
        ).first()

        if not usage:
            usage = AITokenUsage(user_id=user_id, date=today, scenario=scenario, tokens_used=0)
            db.session.add(usage)
            db.session.commit()

        return usage

    @staticmethod
    def can_use_token(user, scenario='ai_research'):
        """Check if user has tokens available today"""
        # God mode has unlimited tokens
        if user.role == 'god':
            return True, 999999

        today_usage = AITokenUsage.get_today_usage(user.id, scenario=scenario)
        daily_limit = AITokenConfig.get_token_limit(user.role, scenario=scenario)
        tokens_remaining = daily_limit - today_usage.tokens_used

        return tokens_remaining > 0, tokens_remaining

    @staticmethod
    def consume_token(user_id, scenario='ai_research'):
        """Consume one token for a user"""
        today_usage = AITokenUsage.get_today_usage(user_id, scenario=scenario)
        today_usage.tokens_used += 1
        db.session.commit()
        return today_usage.tokens_used

    @staticmethod
    def get_user_stats(user, scenario='ai_research'):
        """Get token stats for a user"""
        today_usage = AITokenUsage.get_today_usage(user.id, scenario=scenario)
        daily_limit = AITokenConfig.get_token_limit(user.role, scenario=scenario)

        return {
            'used_today': today_usage.tokens_used,
            'daily_limit': daily_limit,
            'remaining': max(0, daily_limit - today_usage.tokens_used),
            'role': user.role,
            'unlimited': user.role == 'god',
            'scenario': scenario
        }

    @staticmethod
    def cleanup_old_records(days=30):
        """Delete token usage records older than N days"""
        cutoff_date = datetime.utcnow().date() - timedelta(days=days)
        deleted = AITokenUsage.query.filter(AITokenUsage.date < cutoff_date).delete()
        db.session.commit()
        return deleted
