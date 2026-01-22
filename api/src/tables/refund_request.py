from uuid import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import ForeignKey

from .base import Base
from .payment import Payment


class RefundRequest(Base):
    __tablename__ = 'refund_request'

    id: Mapped[UUID] = mapped_column(primary_key=True)
    payment_id: Mapped[UUID] = mapped_column(ForeignKey(Payment.id, ondelete='RESTRICT'), unique=True)
    handler_url: Mapped[str] = mapped_column()
    refunded: Mapped[bool] = mapped_column()