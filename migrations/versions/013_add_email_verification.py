"""Add email verification system

Revision ID: 013_add_email_verification
Revises: 012_add_price_decrease
Create Date: 2025-01-18
"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime


# revision identifiers, used by Alembic.
revision = '013_add_email_verification'
down_revision = '012_add_price_decrease'
branch_labels = None
depends_on = None


def upgrade():
    # Use batch operations to check if columns/tables exist
    from alembic import context
    conn = context.get_bind()
    inspector = sa.inspect(conn)

    # Add email_verified column to users table (only if it doesn't exist)
    columns = [col['name'] for col in inspector.get_columns('users')]
    if 'email_verified' not in columns:
        op.add_column('users',
            sa.Column('email_verified', sa.Boolean(), nullable=True, server_default='0')
        )

    # Create email_verifications table (only if it doesn't exist)
    tables = inspector.get_table_names()
    if 'email_verifications' not in tables:
        op.create_table('email_verifications',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('email', sa.String(length=255), nullable=False),
            sa.Column('code', sa.String(length=6), nullable=False),
            sa.Column('purpose', sa.String(length=20), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False, default=datetime.utcnow),
            sa.Column('expires_at', sa.DateTime(), nullable=False),
            sa.Column('used_at', sa.DateTime(), nullable=True),
            sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('last_sent_at', sa.DateTime(), nullable=False, default=datetime.utcnow),
            sa.Column('resend_count', sa.Integer(), nullable=False, server_default='0'),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE')
        )

        # Create indexes (only if table was just created)
        op.create_index('ix_email_verifications_email', 'email_verifications', ['email'])
        op.create_index('ix_email_verifications_user_id', 'email_verifications', ['user_id'])


def downgrade():
    op.drop_index('ix_email_verifications_user_id', 'email_verifications')
    op.drop_index('ix_email_verifications_email', 'email_verifications')
    op.drop_table('email_verifications')
    op.drop_column('users', 'email_verified')
