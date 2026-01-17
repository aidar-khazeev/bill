from typing import Annotated
from uuid import UUID
from decimal import Decimal
from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel, Field, HttpUrl

from services.payment import PaymentService, ChargeInfo, get_payment_service


router = APIRouter()


class ChargeBody(BaseModel):
    user_id: UUID
    roubles: Decimal = Field(gt=0.0)
    handler_url: HttpUrl = Field(description=
        'Клиенту необходимо указать URL, по которому он будет уведомлен о совершении платежа<br>'
        'Обработчик должен принимать post запрос, и должен быть идемпотентным'
    )
    return_url: HttpUrl


@router.post(
    path='/charge',
    description=
    'Создает платеж (payment) посредством внешнего сервиса<br>'
    'Пользователю необходимо перейти по предоставленной ссылке на внешний сервис, и произвести платеж<br>'
    'Если платеж не будет совершен (за некоторый промежуток времени), он будет автоматически отменен'
)
async def charge(
    body: Annotated[ChargeBody, Body()],
    payments_service: Annotated[PaymentService, Depends(get_payment_service)]
) -> ChargeInfo:
    return await payments_service.charge(
        user_id=body.user_id,
        handler_url=str(body.handler_url),
        return_url=str(body.return_url),
        roubles=body.roubles
    )


class RefundBody(BaseModel):
    payment_id: UUID
    handler_url: HttpUrl = Field(description=
        'Клиенту необходимо указать URL, по которому он будет уведомлен о совершении возврата<br>'
        'Обработчик должен принимать post запрос, и должен быть идемпотентным'
    )


@router.post(
    path='/refund',
    description='Создает запрос на совершение возврата<br>'
)
async def refund(
    body: Annotated[RefundBody, Body()],
    payments_service: Annotated[PaymentService, Depends(get_payment_service)]
) -> None:
    await payments_service.refund(
        payment_id=body.payment_id,
        handler_url=str(body.handler_url)
    )
