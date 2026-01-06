from datetime import datetime
from ..extensions import db


class SystemSetting(db.Model):
    __tablename__ = "system_settings"

    key = db.Column(db.String(100), primary_key=True)
    value_int = db.Column(db.Integer, nullable=True)
    value_str = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @staticmethod
    def get_int(key, default=None):
        setting = SystemSetting.query.filter_by(key=key).first()
        if setting and setting.value_int is not None:
            return setting.value_int
        return default
