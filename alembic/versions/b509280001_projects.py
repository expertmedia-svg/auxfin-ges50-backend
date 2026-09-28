"""Project coverage configuration."""
from alembic import op
import sqlalchemy as sa
revision = 'b509280001'
down_revision = 'a4d122090002'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('projects', sa.Column('id', sa.String(36), primary_key=True), sa.Column('name', sa.String(150), nullable=False, unique=True), sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_table('project_groups', sa.Column('group_id', sa.String(36), sa.ForeignKey('whatsapp_groups.id'), primary_key=True), sa.Column('project_id', sa.String(36), sa.ForeignKey('projects.id'), nullable=False))
    op.create_index('ix_project_groups_project_id', 'project_groups', ['project_id'])
    op.create_table('project_expected_groups', sa.Column('id', sa.String(36), primary_key=True), sa.Column('project_id', sa.String(36), sa.ForeignKey('projects.id'), nullable=False), sa.Column('application_id', sa.String(36), sa.ForeignKey('applications.id'), nullable=False), sa.Column('business_id', sa.String(200), nullable=False), sa.UniqueConstraint('project_id', 'application_id', 'business_id'))
    op.create_index('ix_project_expected_groups_project_id', 'project_expected_groups', ['project_id'])

def downgrade():
    op.drop_table('project_expected_groups')
    op.drop_table('project_groups')
    op.drop_table('projects')
