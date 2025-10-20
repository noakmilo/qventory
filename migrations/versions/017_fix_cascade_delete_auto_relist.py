"""Fix cascade delete for auto_relist_rules

Revision ID: 017_fix_cascade_delete
Revises: 015_webhook_null_user_id
Create Date: 2025-10-20 19:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '017_fix_cascade_delete'
down_revision = '015_webhook_null_user_id'
branch_labels = None
depends_on = None


def upgrade():
    # Fix auto_relist_rules foreign key to CASCADE on delete
    op.drop_constraint('auto_relist_rules_user_id_fkey', 'auto_relist_rules', type_='foreignkey')
    op.create_foreign_key(
        'auto_relist_rules_user_id_fkey',
        'auto_relist_rules',
        'users',
        ['user_id'],
        ['id'],
        ondelete='CASCADE'
    )

    # Fix auto_relist_history foreign key to CASCADE on delete
    op.drop_constraint('auto_relist_history_user_id_fkey', 'auto_relist_history', type_='foreignkey')
    op.create_foreign_key(
        'auto_relist_history_user_id_fkey',
        'auto_relist_history',
        'users',
        ['user_id'],
        ['id'],
        ondelete='CASCADE'
    )


def downgrade():
    # Revert to SET NULL behavior
    op.drop_constraint('auto_relist_rules_user_id_fkey', 'auto_relist_rules', type_='foreignkey')
    op.create_foreign_key(
        'auto_relist_rules_user_id_fkey',
        'auto_relist_rules',
        'users',
        ['user_id'],
        ['id']
    )

    op.drop_constraint('auto_relist_history_user_id_fkey', 'auto_relist_history', type_='foreignkey')
    op.create_foreign_key(
        'auto_relist_history_user_id_fkey',
        'auto_relist_history',
        'users',
        ['user_id'],
        ['id']
    )
