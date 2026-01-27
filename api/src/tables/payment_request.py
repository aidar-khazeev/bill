from uuid import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import ForeignKey

from .base import Base
from .payment import Payment


class PaymentRequest(Base):
    __tablename__ = 'payment_request'

    id: Mapped[UUID] = mapped_column(primary_key=True)
    payment_id: Mapped[UUID] = mapped_column(ForeignKey(Payment.id, ondelete='RESTRICT'), unique=True)
    handler_url: Mapped[str | None] = mapped_column(nullable=True)