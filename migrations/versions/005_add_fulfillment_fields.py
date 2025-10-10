"""add fulfillment fields

Revision ID: 005_add_fulfillment_fields
Revises: 004_add_expenses_table
Create Date: 2025-01-10

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '005_add_fulfillment_fields'
down_revision = '004_add_expenses_table'
branch_labels = None
depends_on = None


def upgrade():
    # Add delivered_at and carrier fields to sales table
    with op.batch_alter_table('sales', schema=None) as batch_op:
        batch_op.add_column(sa.Column('delivered_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('carrier', sa.String(length=100), nullable=True))


def downgrade():
    # Remove delivered_at and carrier fields from sales table
    with op.batch_alter_table('sales', schema=None) as batch_op:
        batch_op.drop_column('carrier')
        batch_op.drop_column('delivered_at')
