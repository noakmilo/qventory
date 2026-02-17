"""ai token scenarios

Revision ID: 058_ai_token_scenarios
Revises: 057_update_ai_token_limits
Create Date: 2026-02-17 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "058_ai_token_scenarios"
down_revision = "057_update_ai_token_limits"
branch_labels = None
depends_on = None


def _column_exists(bind, table_name, column_name):
    inspector = sa.inspect(bind)
    cols = [col["name"] for col in inspector.get_columns(table_name)]
    return column_name in cols


def upgrade():
    bind = op.get_bind()

    if not _column_exists(bind, "ai_token_configs", "scenario"):
        op.add_column("ai_token_configs", sa.Column("scenario", sa.String(length=40), nullable=True))
        op.execute("UPDATE ai_token_configs SET scenario = 'ai_research' WHERE scenario IS NULL")
        op.alter_column("ai_token_configs", "scenario", nullable=False)

    if not _column_exists(bind, "ai_token_usage", "scenario"):
        op.add_column("ai_token_usage", sa.Column("scenario", sa.String(length=40), nullable=True))
        op.execute("UPDATE ai_token_usage SET scenario = 'ai_research' WHERE scenario IS NULL")
        op.alter_column("ai_token_usage", "scenario", nullable=False)

    # Update unique constraints
    try:
        op.drop_constraint("ai_token_configs_role_key", "ai_token_configs", type_="unique")
    except Exception:
        pass

    try:
        op.create_unique_constraint("uq_ai_token_configs_role_scenario", "ai_token_configs", ["role", "scenario"])
    except Exception:
        pass

    try:
        op.drop_constraint("unique_user_date", "ai_token_usage", type_="unique")
    except Exception:
        pass

    try:
        op.create_unique_constraint("unique_user_date_scenario", "ai_token_usage", ["user_id", "date", "scenario"])
    except Exception:
        pass

    # Seed feedback_manager configs if missing
    configs = [
        ("free", 3, "Free"),
        ("early_adopter", 3, "Early Adopter"),
        ("premium", 5, "Premium"),
        ("plus", 10, "Plus"),
        ("pro", 20, "Pro"),
        ("god", 999999, "God Mode"),
        ("enterprise", 999999, "Enterprise"),
    ]
    for role, tokens, display_name in configs:
        op.execute(
            sa.text(
                "INSERT INTO ai_token_configs (role, scenario, daily_tokens, display_name, description, created_at, updated_at) "
                "SELECT :role, 'feedback_manager', :tokens, :display_name, :desc, NOW(), NOW() "
                "WHERE NOT EXISTS (SELECT 1 FROM ai_token_configs WHERE role = :role AND scenario = 'feedback_manager')"
            ).bindparams(
                role=role,
                tokens=tokens,
                display_name=display_name,
                desc=f"{tokens} feedback AI replies per day"
            )
        )


def downgrade():
    # Remove feedback_manager configs
    try:
        op.execute("DELETE FROM ai_token_configs WHERE scenario = 'feedback_manager'")
    except Exception:
        pass

    try:
        op.drop_constraint("uq_ai_token_configs_role_scenario", "ai_token_configs", type_="unique")
    except Exception:
        pass

    try:
        op.create_unique_constraint("ai_token_configs_role_key", "ai_token_configs", ["role"])
    except Exception:
        pass

    try:
        op.drop_constraint("unique_user_date_scenario", "ai_token_usage", type_="unique")
    except Exception:
        pass

    try:
        op.create_unique_constraint("unique_user_date", "ai_token_usage", ["user_id", "date"])
    except Exception:
        pass

    op.drop_column("ai_token_usage", "scenario")
    op.drop_column("ai_token_configs", "scenario")
