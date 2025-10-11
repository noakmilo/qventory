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
    op.create_table('import_jobs',
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
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_import_jobs_celery_task_id'), 'import_jobs', ['celery_task_id'], unique=True)
    op.create_index(op.f('ix_import_jobs_status'), 'import_jobs', ['status'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_import_jobs_status'), table_name='import_jobs')
    op.drop_index(op.f('ix_import_jobs_celery_task_id'), table_name='import_jobs')
    op.drop_table('import_jobs')
