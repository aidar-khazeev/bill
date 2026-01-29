from uuid import UUID
from datetime import datetime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import ForeignKey
from typing import Any

from .base import Base
from .refund import Refund


class RefundRequest(Base):
    __tablename__ = 'refund_request'

    id: Mapped[UUID] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(index=True)
    processed_at: Mapped[datetime | None] = mapped_column(index=True, nullable=True)
    refund_id: Mapped[UUID] = mapped_column(ForeignKey(Refund.id, ondelete='RESTRICT'), unique=True)
    handler_url: Mapped[str | None] = mapped_column(nullable=True)
    extra_data: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)