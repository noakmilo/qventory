"""Add link in bio fields to settings.

Revision ID: 036_add_link_bio_fields
Revises: 035_add_ebay_top_rated
Create Date: 2025-01-11 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '036_add_link_bio_fields'
down_revision = '035_add_ebay_top_rated'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('settings', sa.Column('link_bio_slug', sa.String(length=60), nullable=True))
    op.add_column('settings', sa.Column('link_bio_image_url', sa.String(), nullable=True))
    op.add_column('settings', sa.Column('link_bio_bio', sa.Text(), nullable=True))
    op.add_column('settings', sa.Column('link_bio_links_json', sa.Text(), nullable=True))
    op.add_column('settings', sa.Column('link_bio_featured_json', sa.Text(), nullable=True))
    op.create_index('ix_settings_link_bio_slug', 'settings', ['link_bio_slug'], unique=True)


def downgrade():
    op.drop_index('ix_settings_link_bio_slug', table_name='settings')
    op.drop_column('settings', 'link_bio_featured_json')
    op.drop_column('settings', 'link_bio_links_json')
    op.drop_column('settings', 'link_bio_bio')
    op.drop_column('settings', 'link_bio_image_url')
    op.drop_column('settings', 'link_bio_slug')
