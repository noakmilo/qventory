"""Add pickup scheduler tables and settings fields.

Revision ID: 037_add_pickup_scheduler
Revises: 036_add_link_bio_fields
Create Date: 2025-01-11 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '037_add_pickup_scheduler'
down_revision = '036_add_link_bio_fields'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('settings', sa.Column('pickup_scheduler_enabled', sa.Boolean(), nullable=True))
    op.add_column('settings', sa.Column('pickup_availability_mode', sa.String(length=20), nullable=True))
    op.add_column('settings', sa.Column('pickup_specific_dates_json', sa.Text(), nullable=True))
    op.add_column('settings', sa.Column('pickup_weekly_days_json', sa.Text(), nullable=True))
    op.add_column('settings', sa.Column('pickup_start_time', sa.String(length=5), nullable=True))
    op.add_column('settings', sa.Column('pickup_end_time', sa.String(length=5), nullable=True))
    op.add_column('settings', sa.Column('pickup_breaks_json', sa.Text(), nullable=True))
    op.add_column('settings', sa.Column('pickup_slot_minutes', sa.Integer(), nullable=True))
    op.add_column('settings', sa.Column('pickup_address', sa.Text(), nullable=True))
    op.add_column('settings', sa.Column('pickup_contact_email', sa.String(length=255), nullable=True))
    op.add_column('settings', sa.Column('pickup_contact_phone', sa.String(length=50), nullable=True))
    op.add_column('settings', sa.Column('pickup_instructions', sa.Text(), nullable=True))

    op.create_table(
        'pickup_appointments',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('seller_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('buyer_name', sa.String(length=120), nullable=False),
        sa.Column('buyer_email', sa.String(length=255), nullable=False),
        sa.Column('buyer_phone', sa.String(length=50), nullable=True),
        sa.Column('buyer_note', sa.Text(), nullable=True),
        sa.Column('scheduled_start', sa.DateTime(), nullable=False),
        sa.Column('scheduled_end', sa.DateTime(), nullable=False),
        sa.Column('duration_minutes', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('pickup_address', sa.Text(), nullable=True),
        sa.Column('seller_contact_email', sa.String(length=255), nullable=True),
        sa.Column('seller_contact_phone', sa.String(length=50), nullable=True),
        sa.Column('seller_instructions', sa.Text(), nullable=True),
        sa.Column('public_token', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_pickup_appointments_seller_id', 'pickup_appointments', ['seller_id'])
    op.create_index('ix_pickup_appointments_scheduled_start', 'pickup_appointments', ['scheduled_start'])
    op.create_index('ix_pickup_appointments_status', 'pickup_appointments', ['status'])
    op.create_index('ix_pickup_appointments_public_token', 'pickup_appointments', ['public_token'], unique=True)
    op.create_index('ix_pickup_appointments_created_at', 'pickup_appointments', ['created_at'])

    op.create_table(
        'pickup_messages',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('pickup_id', sa.Integer(), sa.ForeignKey('pickup_appointments.id', ondelete='CASCADE'), nullable=False),
        sa.Column('sender_role', sa.String(length=20), nullable=False),
        sa.Column('sender_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_pickup_messages_pickup_id', 'pickup_messages', ['pickup_id'])
    op.create_index('ix_pickup_messages_created_at', 'pickup_messages', ['created_at'])


def downgrade():
    op.drop_index('ix_pickup_messages_created_at', table_name='pickup_messages')
    op.drop_index('ix_pickup_messages_pickup_id', table_name='pickup_messages')
    op.drop_table('pickup_messages')

    op.drop_index('ix_pickup_appointments_created_at', table_name='pickup_appointments')
    op.drop_index('ix_pickup_appointments_public_token', table_name='pickup_appointments')
    op.drop_index('ix_pickup_appointments_status', table_name='pickup_appointments')
    op.drop_index('ix_pickup_appointments_scheduled_start', table_name='pickup_appointments')
    op.drop_index('ix_pickup_appointments_seller_id', table_name='pickup_appointments')
    op.drop_table('pickup_appointments')

    op.drop_column('settings', 'pickup_instructions')
    op.drop_column('settings', 'pickup_contact_phone')
    op.drop_column('settings', 'pickup_contact_email')
    op.drop_column('settings', 'pickup_address')
    op.drop_column('settings', 'pickup_slot_minutes')
    op.drop_column('settings', 'pickup_breaks_json')
    op.drop_column('settings', 'pickup_end_time')
    op.drop_column('settings', 'pickup_start_time')
    op.drop_column('settings', 'pickup_weekly_days_json')
    op.drop_column('settings', 'pickup_specific_dates_json')
    op.drop_column('settings', 'pickup_availability_mode')
    op.drop_column('settings', 'pickup_scheduler_enabled')
