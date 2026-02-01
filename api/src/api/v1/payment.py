from typing import Annotated, Literal, Any
from uuid import UUID
from decimal import Decimal
from fastapi import APIRouter, Body, Depends, Path
from pydantic import BaseModel, Field, HttpUrl

from services.payment import PaymentService, ChargeInfo, get_payment_service


router = APIRouter()


class PaymentBody(BaseModel):
    user_id: UUID
    amount: Decimal = Field(gt=0.0)
    currency: Literal['RUB'] = Field(default='RUB')
    return_url: HttpUrl
    extra_data: dict[str, Any] | None = Field(default=None)
    card_data: dict[str, Any] | None = Field(default=None)


@router.post(
    path='',
    description=
    'Создает платеж (payment) посредством внешнего сервиса<br>'
    'Пользователю необходимо перейти по предоставленной ссылке на внешний сервис, и произвести платеж<br>'
    'Если платеж не будет совершен (за некоторый промежуток времени), он будет автоматически отменен'
)
async def create_payment(
    body: Annotated[PaymentBody, Body()],
    payments_service: Annotated[PaymentService, Depends(get_payment_service)]
) -> ChargeInfo:
    return await payments_service.payment(
        user_id=body.user_id,
        return_url=str(body.return_url),
        amount=body.amount,
        currency=body.currency,
        extra_data=body.extra_data,
        card_data=body.card_data
    )


class RefundBody(BaseModel):
    amount: Decimal = Field(gt=0.0)
    currency: Literal['RUB'] = Field(default='RUB')
    extra_data: dict[str, Any] | None = None


@router.post(
    path='/{payment_id}/refund',
    description='Создает запрос на совершение возврата<br>'
)
async def create_refund(
    payment_id: Annotated[UUID, Path()],
    body: Annotated[RefundBody, Body()],
    payments_service: Annotated[PaymentService, Depends(get_payment_service)]
) -> None:
    await payments_service.refund(
        payment_id=payment_id,
        amount=body.amount,
        currency=body.currency,
        extra_data=body.extra_data
    )
