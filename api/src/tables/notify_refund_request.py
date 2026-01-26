from uuid import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import ForeignKey

from .base import Base
from .refund import Refund


class RefundNotificationRequest(Base):
    __tablename__ = 'refund_notification_request'

    id: Mapped[UUID] = mapped_column(primary_key=True)
    refund_id: Mapped[UUID] = mapped_column(ForeignKey(Refund.id, ondelete='RESTRICT'), unique=True)
    handler_url: Mapped[str] = mapped_column()
    sent_to_topic: Mapped[bool] = mapped_column(default=False)