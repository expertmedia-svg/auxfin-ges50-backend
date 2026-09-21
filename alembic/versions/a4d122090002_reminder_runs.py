"""Persist automatic reminder execution summaries."""
from alembic import op
import sqlalchemy as sa
revision = "a4d122090002"
down_revision = "a4d122090001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("daily_reminder_runs", sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
                    sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
                    sa.Column("result", sa.JSON(), nullable=False))


def downgrade():
    op.drop_table("daily_reminder_runs")
