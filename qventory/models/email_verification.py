from datetime import datetime, timedelta
import secrets
from ..extensions import db


class EmailVerification(db.Model):
    """
    Stores email verification codes for registration and password reset.
    Codes expire after 15 minutes and can be resent with rate limiting.
    """
    __tablename__ = "email_verifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    email = db.Column(db.String(255), nullable=False, index=True)
    code = db.Column(db.String(6), nullable=False)  # 6-digit code
    purpose = db.Column(db.String(20), nullable=False)  # 'registration' or 'password_reset'

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)  # When code was successfully used
    attempts = db.Column(db.Integer, default=0, nullable=False)  # Failed verification attempts

    # Rate limiting for resending codes
    last_sent_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    resend_count = db.Column(db.Integer, default=0, nullable=False)

    # Relationship
    user = db.relationship("User", backref=db.backref("email_verifications", lazy="dynamic", cascade="all, delete-orphan"))

    def __init__(self, user_id, email, purpose='registration', expiry_minutes=15):
        """Create a new verification code"""
        self.user_id = user_id
        self.email = email
        self.purpose = purpose
        self.code = self._generate_code()
        self.created_at = datetime.utcnow()
        self.expires_at = self.created_at + timedelta(minutes=expiry_minutes)
        self.last_sent_at = self.created_at

    @staticmethod
    def _generate_code():
        """Generate a random 6-digit code"""
        return str(secrets.randbelow(1000000)).zfill(6)

    def is_expired(self):
        """Check if code has expired"""
        return datetime.utcnow() > self.expires_at

    def is_used(self):
        """Check if code has already been used"""
        return self.used_at is not None

    def can_resend(self, cooldown_seconds=60):
        """Check if we can resend the code (rate limiting)"""
        if self.resend_count >= 5:  # Max 5 resends
            return False, "Maximum resend attempts reached. Please try again later."

        time_since_last_send = (datetime.utcnow() - self.last_sent_at).total_seconds()
        if time_since_last_send < cooldown_seconds:
            wait_time = int(cooldown_seconds - time_since_last_send)
            return False, f"Please wait {wait_time} seconds before resending."

        return True, None

    def mark_as_used(self):
        """Mark code as successfully used"""
        self.used_at = datetime.utcnow()

    def increment_attempts(self):
        """Increment failed verification attempts"""
        self.attempts += 1

    def resend(self):
        """Generate new code and update resend tracking"""
        self.code = self._generate_code()
        self.created_at = datetime.utcnow()
        self.expires_at = self.created_at + timedelta(minutes=15)
        self.last_sent_at = datetime.utcnow()
        self.resend_count += 1
        self.attempts = 0  # Reset attempts on resend

    @classmethod
    def create_verification(cls, user_id, email, purpose='registration'):
        """Create or update verification code for user"""
        # Invalidate any existing active codes for this user/purpose
        existing = cls.query.filter_by(
            user_id=user_id,
            purpose=purpose,
            used_at=None
        ).all()

        for verification in existing:
            verification.mark_as_used()  # Mark old codes as used

        # Create new verification
        verification = cls(user_id=user_id, email=email, purpose=purpose)
        db.session.add(verification)
        db.session.commit()

        return verification

    @classmethod
    def verify_code(cls, email, code, purpose='registration'):
        """
        Verify a code for given email and purpose.
        Returns (success: bool, message: str, verification: EmailVerification|None)
        """
        verification = cls.query.filter_by(
            email=email,
            code=code,
            purpose=purpose,
            used_at=None
        ).order_by(cls.created_at.desc()).first()

        if not verification:
            return False, "Invalid verification code.", None

        if verification.is_expired():
            return False, "Verification code has expired. Please request a new one.", None

        if verification.attempts >= 5:
            return False, "Too many failed attempts. Please request a new code.", None

        # Success!
        verification.mark_as_used()
        db.session.commit()
        return True, "Email verified successfully!", verification

    @classmethod
    def cleanup_expired(cls):
        """Delete expired and used codes older than 24 hours (cleanup task)"""
        cutoff = datetime.utcnow() - timedelta(hours=24)
        cls.query.filter(
            db.or_(
                cls.expires_at < cutoff,
                db.and_(cls.used_at.isnot(None), cls.used_at < cutoff)
            )
        ).delete()
        db.session.commit()
