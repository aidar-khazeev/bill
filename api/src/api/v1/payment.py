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
    handler_url: HttpUrl
    return_url: HttpUrl


@router.post('/charge')
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
    handler_url: HttpUrl


@router.post('/refund')
async def refund(
    body: Annotated[RefundBody, Body()],
    payments_service: Annotated[PaymentService, Depends(get_payment_service)]
) -> None:
    await payments_service.refund(
        payment_id=body.payment_id,
        handler_url=str(body.handler_url)
    )
