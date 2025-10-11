"""add import_jobs table

Revision ID: 006_add_import_jobs_table
Revises: 005_add_fulfillment_fields
Create Date: 2025-10-10

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '006_add_import_jobs_table'
down_revision = '005_add_fulfillment_fields'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    table_name = 'import_jobs'
    existing_tables = inspector.get_table_names()

    if table_name not in existing_tables:
        op.create_table(
            table_name,
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('celery_task_id', sa.String(length=255), nullable=True),
            sa.Column('status', sa.String(length=50), nullable=True),
            sa.Column('import_mode', sa.String(length=50), nullable=True),
            sa.Column('listing_status', sa.String(length=50), nullable=True),
            sa.Column('total_items', sa.Integer(), nullable=True),
            sa.Column('processed_items', sa.Integer(), nullable=True),
            sa.Column('imported_count', sa.Integer(), nullable=True),
            sa.Column('updated_count', sa.Integer(), nullable=True),
            sa.Column('skipped_count', sa.Integer(), nullable=True),
            sa.Column('error_count', sa.Integer(), nullable=True),
            sa.Column('error_message', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('started_at', sa.DateTime(), nullable=True),
            sa.Column('completed_at', sa.DateTime(), nullable=True),
            sa.Column('notified', sa.Boolean(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id')
        )

    existing_indexes = {index['name'] for index in inspector.get_indexes(table_name)} if table_name in existing_tables else set()

    if op.f('ix_import_jobs_celery_task_id') not in existing_indexes:
        op.create_index(op.f('ix_import_jobs_celery_task_id'), table_name, ['celery_task_id'], unique=True)

    if op.f('ix_import_jobs_status') not in existing_indexes:
        op.create_index(op.f('ix_import_jobs_status'), table_name, ['status'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_import_jobs_status'), table_name='import_jobs')
    op.drop_index(op.f('ix_import_jobs_celery_task_id'), table_name='import_jobs')
    op.drop_table('import_jobs')
