"""Add sold tracking to items

Revision ID: 019_add_sold_tracking
Revises: 018_add_last_poll_at_to_credentials
Create Date: 2025-01-22

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '019_add_sold_tracking'
down_revision = '018_add_last_poll_at_to_credentials'
branch_labels = None
depends_on = None

def upgrade():
    # Add sold_at and sold_price columns to items table
    op.add_column('items', sa.Column('sold_at', sa.DateTime(), nullable=True))
    op.add_column('items', sa.Column('sold_price', sa.Float(), nullable=True))
    
    # Create index for sold items queries
    op.create_index('idx_items_sold_at', 'items', ['sold_at'], unique=False)

def downgrade():
    op.drop_index('idx_items_sold_at', table_name='items')
    op.drop_column('items', 'sold_price')
    op.drop_column('items', 'sold_at')
