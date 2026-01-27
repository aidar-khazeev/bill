from typing import Annotated, Literal
from uuid import UUID
from decimal import Decimal
from fastapi import APIRouter, Body, Depends, Path
from pydantic import BaseModel, Field, HttpUrl

from services.payment import PaymentService, ChargeInfo, get_payment_service


router = APIRouter()


class ChargeBody(BaseModel):
    user_id: UUID
    amount: Decimal = Field(gt=0.0)
    currency: Literal['RUB'] = Field(default='RUB')
    handler_url: HttpUrl | None = Field(description=
        'Клиенту необходимо указать URL, по которому он будет уведомлен о совершении платежа<br>'
        'Обработчик должен принимать post запрос, и должен быть идемпотентным'
    )
    return_url: HttpUrl


@router.post(
    path='',
    description=
    'Создает платеж (payment) посредством внешнего сервиса<br>'
    'Пользователю необходимо перейти по предоставленной ссылке на внешний сервис, и произвести платеж<br>'
    'Если платеж не будет совершен (за некоторый промежуток времени), он будет автоматически отменен'
)
async def create_payment(
    body: Annotated[ChargeBody, Body()],
    payments_service: Annotated[PaymentService, Depends(get_payment_service)]
) -> ChargeInfo:
    return await payments_service.charge(
        user_id=body.user_id,
        handler_url=str(body.handler_url) if body.handler_url else None,
        return_url=str(body.return_url),
        amount=body.amount,
        currency=body.currency
    )


class RefundBody(BaseModel):
    amount: Decimal = Field(gt=0.0)
    currency: Literal['RUB'] = Field(default='RUB')
    handler_url: HttpUrl | None = Field(description=
        'Клиенту необходимо указать URL, по которому он будет уведомлен о совершении возврата<br>'
        'Обработчик должен принимать post запрос, и должен быть идемпотентным'
    )


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
        handler_url=str(body.handler_url) if body.handler_url else None,
        amount=body.amount,
        currency=body.currency
    )
