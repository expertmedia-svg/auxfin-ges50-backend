from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base
from app.models.common import UUIDMixin, TimestampMixin

class Project(UUIDMixin, TimestampMixin, Base):
    __tablename__ = 'projects'
    name: Mapped[str] = mapped_column(String(150), unique=True)

class ProjectGroup(Base):
    __tablename__ = 'project_groups'
    group_id: Mapped[str] = mapped_column(ForeignKey('whatsapp_groups.id'), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id'), index=True)

class ProjectExpectedGroup(UUIDMixin, Base):
    __tablename__ = 'project_expected_groups'
    __table_args__ = (UniqueConstraint('project_id', 'application_id', 'business_id'),)
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id'), index=True)
    application_id: Mapped[str] = mapped_column(ForeignKey('applications.id'))
    business_id: Mapped[str] = mapped_column(String(200))
