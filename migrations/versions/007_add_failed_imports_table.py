"""add failed_imports table

Revision ID: 007_add_failed_imports_table
Revises: 006_add_import_jobs_table
Create Date: 2025-10-11

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '007_add_failed_imports_table'
down_revision = '006_add_import_jobs_table'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    table_name = 'failed_imports'
    existing_tables = inspector.get_table_names()

    if table_name not in existing_tables:
        op.create_table(
            table_name,
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('import_job_id', sa.Integer(), nullable=True),
            sa.Column('ebay_listing_id', sa.String(length=50), nullable=True),
            sa.Column('ebay_title', sa.String(length=500), nullable=True),
            sa.Column('ebay_sku', sa.String(length=100), nullable=True),
            sa.Column('error_type', sa.String(length=50), nullable=True),
            sa.Column('error_message', sa.Text(), nullable=True),
            sa.Column('raw_data', sa.Text(), nullable=True),
            sa.Column('retry_count', sa.Integer(), nullable=True),
            sa.Column('last_retry_at', sa.DateTime(), nullable=True),
            sa.Column('resolved', sa.Boolean(), nullable=True),
            sa.Column('resolved_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.ForeignKeyConstraint(['import_job_id'], ['import_jobs.id']),
            sa.PrimaryKeyConstraint('id')
        )

        existing_indexes = {index['name'] for index in inspector.get_indexes(table_name)} if table_name in existing_tables else set()

        if 'ix_failed_imports_ebay_listing_id' not in existing_indexes:
            op.create_index(op.f('ix_failed_imports_ebay_listing_id'), table_name, ['ebay_listing_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_failed_imports_ebay_listing_id'), table_name='failed_imports')
    op.drop_table('failed_imports')
