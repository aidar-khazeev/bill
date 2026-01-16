from uuid import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import ForeignKey

from .base import Base
from .payment import Payment


class CaptureRequest(Base):
    __tablename__ = 'capture_request'

    id: Mapped[UUID] = mapped_column(primary_key=True, index=True)
    payment_id: Mapped[UUID] = mapped_column(ForeignKey(Payment.id), index=True)
    charge_handler_url: Mapped[str] = mapped_column()