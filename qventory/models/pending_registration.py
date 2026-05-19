from datetime import datetime, timedelta
import secrets

from ..extensions import db


class PendingRegistration(db.Model):
    """Temporary signup record promoted to User only after email verification."""

    __tablename__ = "pending_registrations"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    code = db.Column(db.String(6), nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)
    attempts = db.Column(db.Integer, default=0, nullable=False)
    last_sent_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    resend_count = db.Column(db.Integer, default=0, nullable=False)

    ref_source = db.Column(db.String(64), nullable=True, index=True)
    ref_medium = db.Column(db.String(64), nullable=True)
    ref_campaign = db.Column(db.String(128), nullable=True)
    ref_content = db.Column(db.String(128), nullable=True)
    ref_term = db.Column(db.String(128), nullable=True)
    ref_landing_path = db.Column(db.String(255), nullable=True)
    ref_first_touch_at = db.Column(db.DateTime, nullable=True)

    def __init__(self, email, username, password_hash, expiry_minutes=30):
        self.email = email
        self.username = username
        self.password_hash = password_hash
        self.code = self._generate_code()
        self.created_at = datetime.utcnow()
        self.expires_at = self.created_at + timedelta(minutes=expiry_minutes)
        self.last_sent_at = self.created_at

    @staticmethod
    def _generate_code():
        return str(secrets.randbelow(1000000)).zfill(6)

    def is_expired(self):
        return datetime.utcnow() > self.expires_at

    def can_resend(self, cooldown_seconds=60):
        if self.resend_count >= 5:
            return False, "Maximum resend attempts reached. Please try again later."

        time_since_last_send = (datetime.utcnow() - self.last_sent_at).total_seconds()
        if time_since_last_send < cooldown_seconds:
            wait_time = int(cooldown_seconds - time_since_last_send)
            return False, f"Please wait {wait_time} seconds before resending."

        return True, None

    def reset_code(self, expiry_minutes=30):
        self.code = self._generate_code()
        self.created_at = datetime.utcnow()
        self.expires_at = self.created_at + timedelta(minutes=expiry_minutes)
        self.last_sent_at = self.created_at
        self.resend_count += 1
        self.attempts = 0
        self.used_at = None

    def mark_as_used(self):
        self.used_at = datetime.utcnow()

    def increment_attempts(self):
        self.attempts += 1

    @classmethod
    def verify_code(cls, email, code):
        pending = cls.query.filter_by(
            email=email,
            code=code,
            used_at=None,
        ).order_by(cls.created_at.desc()).first()

        if not pending:
            pending = cls.query.filter_by(
                email=email,
                used_at=None,
            ).order_by(cls.created_at.desc()).first()
            return False, "Invalid verification code.", pending

        if pending.is_expired():
            return False, "Verification code has expired. Please request a new one.", pending

        if pending.attempts >= 5:
            return False, "Too many failed attempts. Please request a new code.", pending

        pending.mark_as_used()
        return True, "Email verified successfully!", pending

    @classmethod
    def cleanup_expired(cls):
        cutoff = datetime.utcnow() - timedelta(hours=24)
        cls.query.filter(
            db.or_(
                cls.expires_at < cutoff,
                db.and_(cls.used_at.isnot(None), cls.used_at < cutoff),
            )
        ).delete()
        db.session.commit()
