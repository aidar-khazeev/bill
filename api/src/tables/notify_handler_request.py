from uuid import UUID
from datetime import datetime
from typing import Any
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class HandlerNotificationRequest(Base):
    __tablename__ = 'handler_notification_request'

    id: Mapped[UUID] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(index=True)
    processed_at: Mapped[datetime | None] = mapped_column(index=True, nullable=True)
    handler_url: Mapped[str] = mapped_column()
    data: Mapped[dict[str, Any]] = mapped_column()