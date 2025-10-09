"""add last_login to users

Revision ID: 002_add_last_login
Revises: 001_initial_schema
Create Date: 2025-10-08 19:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '002_add_last_login'
down_revision = '001_initial_schema'
branch_labels = None
depends_on = None


def upgrade():
    # Add last_login column to users table
    op.add_column('users', sa.Column('last_login', sa.DateTime(), nullable=True))


def downgrade():
    # Remove last_login column from users table
    op.drop_column('users', 'last_login')
