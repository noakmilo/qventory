"""add help center articles

Revision ID: 031_add_help_articles
Revises: 030_add_ebay_finance_cache
Create Date: 2026-01-06 23:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '031_add_help_articles'
down_revision = '030_add_ebay_finance_cache'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'help_articles' not in existing_tables:
        op.create_table(
            'help_articles',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('slug', sa.String(length=120), nullable=False),
            sa.Column('title', sa.String(length=200), nullable=False),
            sa.Column('summary', sa.String(length=300), nullable=True),
            sa.Column('body_md', sa.Text(), nullable=False),
            sa.Column('is_published', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('slug')
        )

    indexes = {idx['name'] for idx in inspector.get_indexes('help_articles')} if 'help_articles' in existing_tables else set()
    if 'ix_help_articles_slug' not in indexes:
        op.create_index('ix_help_articles_slug', 'help_articles', ['slug'], unique=False)


def downgrade():
    op.drop_index('ix_help_articles_slug', table_name='help_articles')
    op.drop_table('help_articles')
