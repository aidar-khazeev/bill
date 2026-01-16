from typing import Annotated
from uuid import UUID
from decimal import Decimal
from fastapi import APIRouter, Body, Depends
from pydantic import HttpUrl

from services.payment import PaymentService, ChargeInfo, get_payment_service


router = APIRouter()


@router.post('/charge')
async def charge(
    user_id: Annotated[UUID, Body()],
    amount: Annotated[Decimal, Body()],
    handler_url: Annotated[HttpUrl, Body()],
    payments_service: Annotated[PaymentService, Depends(get_payment_service)],
    return_url: Annotated[HttpUrl, Body()],
) -> ChargeInfo:
    return await payments_service.charge(
        user_id=user_id,
        handler_url=str(handler_url),
        return_url=str(return_url),
        roubles=amount
    )


@router.post('/refund')
async def refund(
    payment_id: Annotated[UUID, Body()],
    handler_url: Annotated[HttpUrl, Body()],
    payments_service: Annotated[PaymentService, Depends(get_payment_service)]
) -> None:
    await payments_service.refund(
        payment_id=payment_id,
        handler_url=str(handler_url)
    )
