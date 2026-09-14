"""Persist correction tasks and outgoing reminder attempts."""
from alembic import op
import sqlalchemy as sa

revision = "72ac901b3410"
down_revision = "1cecbd439794"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "evidence_followups",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("evidence_id", sa.String(36), sa.ForeignKey("evidence_files.id"), nullable=False, unique=True),
        sa.Column("reason", sa.String(2000), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("send_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("replacement_evidence_id", sa.String(36), sa.ForeignKey("evidence_files.id")),
        sa.Column("resolved_at", sa.DateTime()),
    )
    op.create_index("ix_evidence_followups_status", "evidence_followups", ["status"])
    op.create_table(
        "followup_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("followup_id", sa.String(36), sa.ForeignKey("evidence_followups.id"), nullable=False),
        sa.Column("requested_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("recipient", sa.String(150), nullable=False),
        sa.Column("body", sa.String(4000), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("external_message_id", sa.String(200)),
        sa.Column("error", sa.String(500)),
    )
    op.create_index("ix_followup_messages_followup_id", "followup_messages", ["followup_id"])


def downgrade():
    op.drop_table("followup_messages")
    op.drop_table("evidence_followups")
