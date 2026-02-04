"""add support ticket tables

Revision ID: 039_add_support_tickets
Revises: 038_add_user_trial_flag
Create Date: 2026-02-04
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = '039_add_support_tickets'
down_revision = '038_add_user_trial_flag'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table('support_tickets'):
        op.create_table(
            'support_tickets',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('ticket_code', sa.String(length=32), nullable=False),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('subject', sa.String(length=200), nullable=False),
            sa.Column('status', sa.String(length=20), nullable=False, server_default='open'),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.Column('closed_at', sa.DateTime(), nullable=True),
            sa.Column('resolved_at', sa.DateTime(), nullable=True),
        )
        op.create_index('ix_support_tickets_ticket_code', 'support_tickets', ['ticket_code'], unique=True)
        op.create_index('ix_support_tickets_user_id', 'support_tickets', ['user_id'], unique=False)
        op.create_index('ix_support_tickets_status', 'support_tickets', ['status'], unique=False)

    if not inspector.has_table('support_messages'):
        op.create_table(
            'support_messages',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('ticket_id', sa.Integer(), sa.ForeignKey('support_tickets.id'), nullable=False),
            sa.Column('sender_role', sa.String(length=20), nullable=False),
            sa.Column('body', sa.Text(), nullable=False),
            sa.Column('is_read_by_user', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('is_read_by_admin', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('created_at', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_support_messages_ticket_id', 'support_messages', ['ticket_id'], unique=False)

    if not inspector.has_table('support_attachments'):
        op.create_table(
            'support_attachments',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('message_id', sa.Integer(), sa.ForeignKey('support_messages.id'), nullable=False),
            sa.Column('image_url', sa.String(length=500), nullable=False),
            sa.Column('public_id', sa.String(length=255), nullable=True),
            sa.Column('filename', sa.String(length=255), nullable=True),
            sa.Column('bytes', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_support_attachments_message_id', 'support_attachments', ['message_id'], unique=False)


def downgrade():
    op.drop_index('ix_support_attachments_message_id', table_name='support_attachments')
    op.drop_table('support_attachments')
    op.drop_index('ix_support_messages_ticket_id', table_name='support_messages')
    op.drop_table('support_messages')
    op.drop_index('ix_support_tickets_status', table_name='support_tickets')
    op.drop_index('ix_support_tickets_user_id', table_name='support_tickets')
    op.drop_index('ix_support_tickets_ticket_code', table_name='support_tickets')
    op.drop_table('support_tickets')
