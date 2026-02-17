"""update ai token limits

Revision ID: 057_update_ai_token_limits
Revises: 056_feedback_response_source
Create Date: 2026-02-17 00:00:00.000000
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "057_update_ai_token_limits"
down_revision = "056_feedback_response_source"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE ai_token_configs SET daily_tokens = 3 WHERE role = 'early_adopter'")
    op.execute("UPDATE ai_token_configs SET daily_tokens = 5 WHERE role = 'premium'")
    op.execute("UPDATE ai_token_configs SET daily_tokens = 10 WHERE role = 'plus'")
    op.execute("UPDATE ai_token_configs SET daily_tokens = 20 WHERE role = 'pro'")


def downgrade():
    # No-op: keep current limits on downgrade
    pass
