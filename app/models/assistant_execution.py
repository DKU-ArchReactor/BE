"""Short-lived server-only snapshot store, separate from chat text and usage."""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Index, JSON, String
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class AssistantExecution(Base):
    __tablename__ = 'assistant_executions'
    __table_args__ = (Index('ix_assistant_execution_owner_created', 'user_id', 'created_at'),
                      Index('ix_assistant_execution_expires', 'expires_at'))
    execution_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(50), ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False)
    artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    result_version: Mapped[str] = mapped_column(String(64), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
