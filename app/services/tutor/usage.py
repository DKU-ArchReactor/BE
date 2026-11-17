from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.assistant_usage import AssistantUsage


def reserve_request(db: Session, user_id: str, *, now: datetime | None = None) -> None:
    """Atomic allowance shared by all workers. Failed/cancelled attempts count too."""
    now = now or datetime.now(timezone.utc)
    usage = AssistantUsage.__table__
    statement = insert(usage).values(
        user_id=user_id, usage_date=now.date(), request_count=1, last_requested_at=now,
    ).on_conflict_do_update(
        index_elements=[usage.c.user_id, usage.c.usage_date],
        set_={'request_count': usage.c.request_count + 1, 'last_requested_at': now},
        where=(usage.c.request_count < settings.ASSISTANT_DAILY_REQUESTS)
        & (usage.c.last_requested_at <= now - timedelta(seconds=settings.ASSISTANT_COOLDOWN_SECONDS)),
    ).returning(usage.c.request_count)
    try:
        accepted = db.execute(statement).scalar_one_or_none()
        db.commit()
    except Exception:
        db.rollback()
        raise
    if accepted is None:
        raise HTTPException(429, {
            'code': 'ASSISTANT_RATE_LIMIT',
            'message': '요청 간격 또는 오늘의 AI 질문 한도를 초과했습니다. 잠시 후 또는 내일 다시 시도해 주세요.',
        })
