"""Persist unverified visual observations separately from validated extraction."""
from alembic import op
import sqlalchemy as sa

revision = "93b820f41602"
down_revision = "72ac901b3410"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("evidence_extractions", sa.Column("ai_observations", sa.JSON(), nullable=False, server_default="[]"))


def downgrade():
    op.drop_column("evidence_extractions", "ai_observations")
