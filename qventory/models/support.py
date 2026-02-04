from datetime import datetime
import random
import string

from ..extensions import db


class SupportTicket(db.Model):
    __tablename__ = "support_tickets"

    id = db.Column(db.Integer, primary_key=True)
    ticket_code = db.Column(db.String(32), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    subject = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="open", index=True)  # open, resolved, closed
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    closed_at = db.Column(db.DateTime, nullable=True)
    resolved_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship("User", backref=db.backref("support_tickets", lazy="dynamic", cascade="all, delete-orphan"))
    messages = db.relationship("SupportMessage", backref="ticket", lazy="dynamic", cascade="all, delete-orphan")

    @staticmethod
    def generate_ticket_code():
        date_part = datetime.utcnow().strftime("%Y%m%d")
        rand_part = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        return f"SUP-{date_part}-{rand_part}"


class SupportMessage(db.Model):
    __tablename__ = "support_messages"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("support_tickets.id"), nullable=False, index=True)
    sender_role = db.Column(db.String(20), nullable=False)  # user, admin
    body = db.Column(db.Text, nullable=False)
    is_read_by_user = db.Column(db.Boolean, default=False, nullable=False)
    is_read_by_admin = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    attachments = db.relationship("SupportAttachment", backref="message", lazy="dynamic", cascade="all, delete-orphan")


class SupportAttachment(db.Model):
    __tablename__ = "support_attachments"

    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey("support_messages.id"), nullable=False, index=True)
    image_url = db.Column(db.String(500), nullable=False)
    public_id = db.Column(db.String(255), nullable=True)
    filename = db.Column(db.String(255), nullable=True)
    bytes = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
