from datetime import datetime
from ..extensions import db
from cryptography.fernet import Fernet
import os

class MarketplaceCredential(db.Model):
    """
    Almacena credenciales de API para marketplaces (eBay, Mercari, Depop, Whatnot)
    Encripta tokens y secrets para seguridad
    """
    __tablename__ = "marketplace_credentials"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    # Marketplace
    marketplace = db.Column(db.String(50), nullable=False, index=True)  # ebay, mercari, depop, whatnot

    # Credenciales (encriptadas)
    app_id = db.Column(db.Text, nullable=True)  # Client ID / App ID
    cert_id = db.Column(db.Text, nullable=True)  # Client Secret / Cert ID
    dev_id = db.Column(db.Text, nullable=True)  # Developer ID (eBay)

    # OAuth tokens (encriptados)
    access_token = db.Column(db.Text, nullable=True)
    refresh_token = db.Column(db.Text, nullable=True)
    token_expires_at = db.Column(db.DateTime, nullable=True)

    # eBay user information
    ebay_user_id = db.Column(db.String(100), nullable=True)  # eBay username/user ID
    ebay_top_rated = db.Column(db.Boolean, nullable=True, default=False)

    # eBay Store Subscription (monthly cost in USD)
    ebay_store_subscription = db.Column(db.Float, nullable=True, default=0.0)  # Monthly subscription fee (Basic: 27.95, Premium: 74.95, etc.)
    ebay_store_subscription_level = db.Column(db.String(50), nullable=True)  # STARTER, BASIC, PREMIUM, ANCHOR, ENTERPRISE

    # Estado
    is_active = db.Column(db.Boolean, default=True, index=True)
    last_synced_at = db.Column(db.DateTime, nullable=True)
    last_poll_at = db.Column(db.DateTime, nullable=True)  # Last time we polled for new listings
    poll_cooldown_until = db.Column(db.DateTime, nullable=True)  # Backoff after rate limit
    poll_cooldown_reason = db.Column(db.String(255), nullable=True)
    sync_status = db.Column(db.String(50), nullable=True)  # success, error, pending
    error_message = db.Column(db.Text, nullable=True)

    # Metadata
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Unique constraint: un user solo puede tener una credencial activa por marketplace
    __table_args__ = (
        db.UniqueConstraint('user_id', 'marketplace', name='unique_user_marketplace'),
    )

    @staticmethod
    def get_encryption_key():
        """Get or create encryption key from environment"""
        key = os.environ.get("ENCRYPTION_KEY")
        if not key:
            # Generate a new key if not exists (store in .env!)
            key = Fernet.generate_key().decode()
            print(f"⚠️  WARNING: Generated new ENCRYPTION_KEY. Add to .env: ENCRYPTION_KEY={key}")
        return key.encode() if isinstance(key, str) else key

    def encrypt_field(self, value):
        """Encrypt sensitive field"""
        if not value:
            return None
        f = Fernet(self.get_encryption_key())
        return f.encrypt(value.encode()).decode()

    def decrypt_field(self, encrypted_value):
        """Decrypt sensitive field"""
        if not encrypted_value:
            return None
        f = Fernet(self.get_encryption_key())
        return f.decrypt(encrypted_value.encode()).decode()

    # Properties para acceso fácil a campos encriptados
    def set_app_id(self, value):
        self.app_id = self.encrypt_field(value)

    def get_app_id(self):
        return self.decrypt_field(self.app_id)

    def set_cert_id(self, value):
        self.cert_id = self.encrypt_field(value)

    def get_cert_id(self):
        return self.decrypt_field(self.cert_id)

    def set_dev_id(self, value):
        self.dev_id = self.encrypt_field(value)

    def get_dev_id(self):
        return self.decrypt_field(self.dev_id)

    def set_access_token(self, value):
        self.access_token = self.encrypt_field(value)

    def get_access_token(self):
        return self.decrypt_field(self.access_token)

    def set_refresh_token(self, value):
        self.refresh_token = self.encrypt_field(value)

    def get_refresh_token(self):
        return self.decrypt_field(self.refresh_token)
