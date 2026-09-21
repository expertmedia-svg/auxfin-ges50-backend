"""Daily recipient reservation prevents repeated automatic messages."""
from alembic import op
import sqlalchemy as sa
revision = "a4d122090001"
down_revision = "93b820f41602"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("daily_reminders", sa.Column("day", sa.String(10), primary_key=True),
                    sa.Column("recipient", sa.String(150), primary_key=True),
                    sa.Column("status", sa.String(20), nullable=False))


def downgrade():
    op.drop_table("daily_reminders")
