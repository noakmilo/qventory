"""add webhook tables

Revision ID: 014_add_webhook_tables
Revises: 013_add_email_verification
Create Date: 2025-10-20 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '014_add_webhook_tables'
down_revision = '013_add_email_verification'
branch_labels = None
depends_on = None


def upgrade():
    # Create webhook_subscriptions table
    op.create_table(
        'webhook_subscriptions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('subscription_id', sa.String(length=100), nullable=False),
        sa.Column('topic', sa.String(length=100), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('last_renewed_at', sa.DateTime(), nullable=True),
        sa.Column('renewal_attempts', sa.Integer(), nullable=True),
        sa.Column('delivery_url', sa.String(length=500), nullable=False),
        sa.Column('filter_criteria', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('event_count', sa.Integer(), nullable=True),
        sa.Column('last_event_at', sa.DateTime(), nullable=True),
        sa.Column('error_count', sa.Integer(), nullable=True),
        sa.Column('last_error_at', sa.DateTime(), nullable=True),
        sa.Column('last_error_message', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('subscription_id')
    )
    op.create_index(
        'ix_webhook_subscriptions_user_id',
        'webhook_subscriptions',
        ['user_id'],
        unique=False
    )
    op.create_index(
        'ix_webhook_subscriptions_status',
        'webhook_subscriptions',
        ['status'],
        unique=False
    )
    op.create_index(
        'ix_webhook_subscriptions_expires_at',
        'webhook_subscriptions',
        ['expires_at'],
        unique=False
    )

    # Create webhook_events table
    op.create_table(
        'webhook_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('subscription_id', sa.Integer(), nullable=True),
        sa.Column('event_id', sa.String(length=100), nullable=False),
        sa.Column('topic', sa.String(length=100), nullable=False),
        sa.Column('payload', postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column('headers', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=True),
        sa.Column('processed_at', sa.DateTime(), nullable=True),
        sa.Column('processing_attempts', sa.Integer(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('error_details', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('received_at', sa.DateTime(), nullable=False),
        sa.Column('ebay_timestamp', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['subscription_id'], ['webhook_subscriptions.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('event_id')
    )
    op.create_index(
        'ix_webhook_events_user_id',
        'webhook_events',
        ['user_id'],
        unique=False
    )
    op.create_index(
        'ix_webhook_events_status',
        'webhook_events',
        ['status'],
        unique=False
    )
    op.create_index(
        'ix_webhook_events_topic',
        'webhook_events',
        ['topic'],
        unique=False
    )
    op.create_index(
        'ix_webhook_events_received_at',
        'webhook_events',
        ['received_at'],
        unique=False
    )

    # Create webhook_processing_queue table
    op.create_table(
        'webhook_processing_queue',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event_id', sa.Integer(), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=True),
        sa.Column('max_retries', sa.Integer(), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=True),
        sa.Column('next_retry_at', sa.DateTime(), nullable=True),
        sa.Column('celery_task_id', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['event_id'], ['webhook_events.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(
        'ix_webhook_processing_queue_status',
        'webhook_processing_queue',
        ['status'],
        unique=False
    )
    op.create_index(
        'ix_webhook_processing_queue_next_retry_at',
        'webhook_processing_queue',
        ['next_retry_at'],
        unique=False
    )
    op.create_index(
        'ix_webhook_processing_queue_priority',
        'webhook_processing_queue',
        ['priority'],
        unique=False
    )


def downgrade():
    op.drop_index('ix_webhook_processing_queue_priority', table_name='webhook_processing_queue')
    op.drop_index('ix_webhook_processing_queue_next_retry_at', table_name='webhook_processing_queue')
    op.drop_index('ix_webhook_processing_queue_status', table_name='webhook_processing_queue')
    op.drop_table('webhook_processing_queue')

    op.drop_index('ix_webhook_events_received_at', table_name='webhook_events')
    op.drop_index('ix_webhook_events_topic', table_name='webhook_events')
    op.drop_index('ix_webhook_events_status', table_name='webhook_events')
    op.drop_index('ix_webhook_events_user_id', table_name='webhook_events')
    op.drop_table('webhook_events')

    op.drop_index('ix_webhook_subscriptions_expires_at', table_name='webhook_subscriptions')
    op.drop_index('ix_webhook_subscriptions_status', table_name='webhook_subscriptions')
    op.drop_index('ix_webhook_subscriptions_user_id', table_name='webhook_subscriptions')
    op.drop_table('webhook_subscriptions')
