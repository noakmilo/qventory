from datetime import datetime
from ..extensions import db


class ReferralVisit(db.Model):
    __tablename__ = "referral_visits"

    id = db.Column(db.Integer, primary_key=True)
    utm_source = db.Column(db.String(64), nullable=True, index=True)
    utm_medium = db.Column(db.String(64), nullable=True)
    utm_campaign = db.Column(db.String(128), nullable=True)
    utm_content = db.Column(db.String(128), nullable=True)
    utm_term = db.Column(db.String(128), nullable=True)
    landing_path = db.Column(db.String(255), nullable=True)
    session_id = db.Column(db.String(64), nullable=True, index=True)
    ip_hash = db.Column(db.String(64), nullable=True)
    user_agent = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
