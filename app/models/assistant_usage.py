"""Shared request allowance; does not store conversations."""
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AssistantUsage(Base):
    __tablename__ = 'assistant_usage'

    user_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    usage_date: Mapped[date] = mapped_column(Date, primary_key=True)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False)
    last_requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
