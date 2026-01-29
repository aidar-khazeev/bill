from .base import Base
from typing import Literal
from datetime import datetime
from uuid import UUID
from decimal import Decimal
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from .payment import Payment


Status = Literal['created', 'succeeded', 'cancelled']


class Refund(Base):
    __tablename__ = 'refund'

    id: Mapped[UUID] = mapped_column(primary_key=True, index=True)
    payment_id: Mapped[UUID] = mapped_column(ForeignKey(Payment.id, ondelete='RESTRICT'))
    external_id: Mapped[str | None] = mapped_column(index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column()
    status: Mapped[Status] = mapped_column()
    external_cancellation_reason: Mapped[str | None] = mapped_column(nullable=True)

    amount: Mapped[Decimal] = mapped_column()
    currency: Mapped[str] = mapped_column()