from .base import Base
from typing import Literal
from datetime import datetime
from uuid import UUID
from decimal import Decimal
from sqlalchemy.orm import Mapped, mapped_column


Status = Literal['created', 'succeeded', 'cancelled']


class Payment(Base):
    __tablename__ = 'payment'

    id: Mapped[UUID] = mapped_column(primary_key=True, index=True)
    external_id: Mapped[str] = mapped_column(index=True)
    created_at: Mapped[datetime] = mapped_column()
    user_id: Mapped[UUID] = mapped_column(index=True)
    status: Mapped[Status] = mapped_column()
    external_cancellation_reason: Mapped[str | None] = mapped_column(nullable=True)

    amount: Mapped[Decimal] = mapped_column()
    currency: Mapped[str] = mapped_column()