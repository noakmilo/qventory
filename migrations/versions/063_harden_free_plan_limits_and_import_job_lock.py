"""harden free plan limits and import job lock

Revision ID: 063_harden_free_plan_limits_lock
Revises: 062_image_guarantee
Create Date: 2026-04-22 18:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '063_harden_free_plan_limits_lock'
down_revision = '062_image_guarantee'
branch_labels = None
depends_on = None


FREE_PLAN_DEFAULT_MAX_ITEMS = 100
FREE_PLAN_NOT_NULL_CK = 'ck_plan_limits_free_max_items_not_null'
ACTIVE_IMPORT_INDEX = 'ux_import_jobs_user_active'


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    table_names = set(inspector.get_table_names())

    if 'plan_limits' in table_names:
        # Sanitize existing data first so constraint creation cannot fail.
        op.execute(
            sa.text(
                """
                UPDATE plan_limits
                SET max_items = :default_limit
                WHERE plan = 'free' AND max_items IS NULL
                """
            ).bindparams(default_limit=FREE_PLAN_DEFAULT_MAX_ITEMS)
        )

        check_constraints = {
            constraint.get('name')
            for constraint in inspector.get_check_constraints('plan_limits')
        }
        if FREE_PLAN_NOT_NULL_CK not in check_constraints:
            op.create_check_constraint(
                FREE_PLAN_NOT_NULL_CK,
                'plan_limits',
                "plan <> 'free' OR max_items IS NOT NULL",
            )

    if 'import_jobs' in table_names and bind.dialect.name == 'postgresql':
        # Keep only one active job per user by closing extra pending/processing rows.
        op.execute(
            """
            WITH ranked AS (
                SELECT
                    id,
                    user_id,
                    ROW_NUMBER() OVER (
                        PARTITION BY user_id
                        ORDER BY created_at DESC, id DESC
                    ) AS rn
                FROM import_jobs
                WHERE status IN ('pending', 'processing')
            )
            UPDATE import_jobs
            SET
                status = 'failed',
                completed_at = COALESCE(completed_at, NOW()),
                error_message = COALESCE(error_message, 'Closed by migration: duplicate active import job')
            WHERE id IN (
                SELECT id
                FROM ranked
                WHERE rn > 1
            )
            """
        )

        index_names = {idx.get('name') for idx in inspector.get_indexes('import_jobs')}
        if ACTIVE_IMPORT_INDEX not in index_names:
            op.create_index(
                ACTIVE_IMPORT_INDEX,
                'import_jobs',
                ['user_id'],
                unique=True,
                postgresql_where=sa.text("status IN ('pending', 'processing')"),
            )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if 'import_jobs' in table_names and bind.dialect.name == 'postgresql':
        index_names = {idx.get('name') for idx in inspector.get_indexes('import_jobs')}
        if ACTIVE_IMPORT_INDEX in index_names:
            op.drop_index(ACTIVE_IMPORT_INDEX, table_name='import_jobs')

    if 'plan_limits' in table_names:
        check_constraints = {
            constraint.get('name')
            for constraint in inspector.get_check_constraints('plan_limits')
        }
        if FREE_PLAN_NOT_NULL_CK in check_constraints:
            op.drop_constraint(FREE_PLAN_NOT_NULL_CK, 'plan_limits', type_='check')
