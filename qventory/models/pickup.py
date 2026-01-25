from datetime import datetime
from qventory.extensions import db


class PickupAppointment(db.Model):
    __tablename__ = "pickup_appointments"

    id = db.Column(db.Integer, primary_key=True)
    seller_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    buyer_name = db.Column(db.String(120), nullable=False)
    buyer_email = db.Column(db.String(255), nullable=False)
    buyer_phone = db.Column(db.String(50))
    buyer_note = db.Column(db.Text)

    scheduled_start = db.Column(db.DateTime, nullable=False, index=True)
    scheduled_end = db.Column(db.DateTime, nullable=False)
    duration_minutes = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), default="scheduled", index=True)

    pickup_address = db.Column(db.Text)
    seller_contact_email = db.Column(db.String(255))
    seller_contact_phone = db.Column(db.String(50))
    seller_instructions = db.Column(db.Text)

    public_token = db.Column(db.String(64), unique=True, nullable=False, index=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    seller = db.relationship(
        "User",
        backref=db.backref("pickup_appointments", lazy="dynamic", cascade="all, delete-orphan")
    )
    messages = db.relationship(
        "PickupMessage",
        backref="appointment",
        lazy="dynamic",
        cascade="all, delete-orphan"
    )


class PickupMessage(db.Model):
    __tablename__ = "pickup_messages"

    id = db.Column(db.Integer, primary_key=True)
    pickup_id = db.Column(db.Integer, db.ForeignKey("pickup_appointments.id", ondelete="CASCADE"), nullable=False, index=True)
    sender_role = db.Column(db.String(20), nullable=False)
    sender_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
