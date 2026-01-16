from uuid import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import ForeignKey

from .base import Base
from .payment import Payment


class ChargeRequest(Base):
    __tablename__ = 'charge_request'

    id: Mapped[UUID] = mapped_column(primary_key=True, index=True)
    payment_id: Mapped[UUID] = mapped_column(ForeignKey(Payment.id), index=True)
    handler_url: Mapped[str] = mapped_column()