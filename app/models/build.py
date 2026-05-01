import enum
import uuid

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.file import File


class BuildStatus(str, enum.Enum):
    success = "success"
    failed = "failed"


class Build(Base):
    __tablename__ = "builds"

    build_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("files.file_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    binary_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    assembly_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    log: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[BuildStatus | None] = mapped_column(
        SAEnum(BuildStatus, name="build_status", native_enum=False, length=16),
        nullable=True,
    )

    file: Mapped[File] = relationship(back_populates="builds")
    sim_logs: Mapped[list["SimLog"]] = relationship(  # noqa: F821
        back_populates="build", cascade="all, delete-orphan"
    )
