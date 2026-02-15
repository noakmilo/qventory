"""polling logs

Revision ID: 051_polling_logs
Revises: 050_ebay_fee_snapshot
Create Date: 2026-02-15 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "051_polling_logs"
down_revision = "050_ebay_fee_snapshot"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS polling_logs (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users (id),
            marketplace VARCHAR(50),
            started_at TIMESTAMP WITHOUT TIME ZONE,
            ended_at TIMESTAMP WITHOUT TIME ZONE,
            window_start TIMESTAMP WITHOUT TIME ZONE,
            window_end TIMESTAMP WITHOUT TIME ZONE,
            new_listings INTEGER,
            errors_count INTEGER,
            error_message TEXT,
            status VARCHAR(20),
            created_at TIMESTAMP WITHOUT TIME ZONE
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_polling_logs_user_id ON polling_logs (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_polling_logs_marketplace ON polling_logs (marketplace)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_polling_logs_status ON polling_logs (status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_polling_logs_created_at ON polling_logs (created_at)")


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_polling_logs_created_at")
    op.execute("DROP INDEX IF EXISTS ix_polling_logs_status")
    op.execute("DROP INDEX IF EXISTS ix_polling_logs_marketplace")
    op.execute("DROP INDEX IF EXISTS ix_polling_logs_user_id")
    op.execute("DROP TABLE IF EXISTS polling_logs")
