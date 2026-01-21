import httpx
import logging
from functools import lru_cache
from fastapi import Depends
from datetime import datetime
from uuid import UUID, uuid4
from decimal import Decimal
from typing import Annotated
from dataclasses import dataclass
from pydantic import BaseModel, HttpUrl
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from sqlalchemy import insert

import db.postgres
import tables
from settings import yookassa_settings


logger = logging.getLogger('payment-service')


class PaymentDoesntExistError(Exception):
    ...


class ExternalPaymentServiceError(Exception):
    ...


class ChargeInfo(BaseModel):
    payment_id: UUID
    confirmation_url: HttpUrl


@dataclass(frozen=True)
class PaymentService:
    session_maker: async_sessionmaker[AsyncSession]
    yookassa_client: httpx.AsyncClient

    async def charge(self, user_id: UUID, handler_url: str, return_url: str, roubles: Decimal):
        payment_id = uuid4()

        # https://yookassa.ru/developers/api#create_payment
        try:
            response = await self.yookassa_client.post(
                url='/v3/payments',
                headers={'Idempotence-Key': str(uuid4())},
                json={
                    'amount': {
                        'value': str(roubles),
                        'currency': 'RUB'
                    },
                    'confirmation': {
                        'type': 'redirect',
                        'return_url': str(return_url)
                    },
                    # Проходим 2 стадии
                    # https://yookassa.ru/developers/payment-acceptance/getting-started/payment-process#capture-and-cancel
                    'capture': False,
                    'metadata': {
                        'payment_id': str(payment_id),
                        'handler_url': handler_url
                    }
                }
            )
        except httpx.ConnectError as e:
            logger.error(f'connection error: {str(e)}')
            raise ExternalPaymentServiceError()

        if response.status_code != 200:
            logger.error(f'{response.status_code}: {response.text}')
            raise ExternalPaymentServiceError()

        # При ошибке, если payment все же создался,
        # страницу для перенаправления пользователь не получит, и не подтвердит оплату.
        # Payment будет в статусе `pending`, через некоторое время перейдет в `expired_on_confirmation`
        # https://yookassa.ru/developers/payment-acceptance/getting-started/payment-process#user-confirmation

        response_json = response.json()

        async with self.session_maker() as session:
            await session.execute(insert(tables.Payment).values({
                tables.Payment.id: payment_id,
                tables.Payment.external_id: response_json['id'],
                tables.Payment.user_id: user_id,
                tables.Payment.created_at: datetime.now(),
                tables.Payment.roubles: roubles,
                tables.Payment.status: 'created'
            }))
            await session.commit()

        return ChargeInfo(
            payment_id=payment_id,
            confirmation_url=HttpUrl(response_json['confirmation']['confirmation_url'])
        )

    async def refund(self, payment_id: UUID, handler_url: str):
        async with self.session_maker() as session:
            payment = await session.get(tables.Payment, payment_id)
            if payment is None:
                raise PaymentDoesntExistError()

            # Будет проверен один раз в отдельном процессе,
            # если post запрос не завершится успешно
            await session.execute(insert(tables.RefundRequest).values({
                tables.RefundRequest.id: uuid4(),
                tables.RefundRequest.payment_id: payment_id,
                tables.RefundRequest.handler_url: handler_url
            }))
            await session.commit()


@lru_cache
def get_payment_service(
    session_maker: Annotated[async_sessionmaker[AsyncSession], Depends(db.postgres.get_session_maker)]
) -> PaymentService:
    return PaymentService(
        session_maker=session_maker,
        yookassa_client=httpx.AsyncClient(
            base_url='https://api.yookassa.ru',
            auth=httpx.BasicAuth(yookassa_settings.shop_id, yookassa_settings.secret_key)
        )
    )