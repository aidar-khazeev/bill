import httpx
import logging
from functools import lru_cache
from datetime import datetime
from uuid import UUID, uuid4
from decimal import Decimal
from dataclasses import dataclass
from pydantic import BaseModel, HttpUrl
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
    yookassa_client: httpx.AsyncClient

    async def charge(
        self, user_id: UUID, handler_url: str, return_url: str,
        amount: Decimal, currency: str
    ):
        payment_id = uuid4()

        # https://yookassa.ru/developers/api#create_payment
        try:
            response = await self.yookassa_client.post(
                url='/v3/payments',
                headers={'Idempotence-Key': str(uuid4())},
                json={
                    'amount': {
                        'value': str(amount),
                        'currency': currency
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
            logger.error(f'got status code {response.status_code}: {response.text}')
            raise ExternalPaymentServiceError()

        # При ошибке, если payment все же создался,
        # страницу для перенаправления пользователь не получит, и не подтвердит оплату.
        # Payment будет в статусе `pending`, через некоторое время перейдет в `expired_on_confirmation`
        # https://yookassa.ru/developers/payment-acceptance/getting-started/payment-process#user-confirmation

        response_json = response.json()

        async with db.postgres.session_maker() as session:
            await session.execute(insert(tables.Payment).values({
                tables.Payment.id: payment_id,
                tables.Payment.external_id: response_json['id'],
                tables.Payment.user_id: user_id,
                tables.Payment.created_at: datetime.now(),
                tables.Payment.amount: amount,
                tables.Payment.currency: currency,
                tables.Payment.status: 'created'
            }))
            await session.commit()

        return ChargeInfo(
            payment_id=payment_id,
            confirmation_url=HttpUrl(response_json['confirmation']['confirmation_url'])
        )

    async def refund(self, payment_id: UUID, handler_url: str):
        async with db.postgres.session_maker() as session:
            payment = await session.get(tables.Payment, payment_id)
            if payment is None:
                raise PaymentDoesntExistError()

            # Будет проверен один раз в отдельном процессе,
            # если post запрос не завершится успешно
            await session.execute(insert(tables.RefundRequest).values({
                tables.RefundRequest.id: uuid4(),
                tables.RefundRequest.payment_id: payment_id,
                tables.RefundRequest.handler_url: handler_url,
                tables.RefundRequest.refunded: False
            }))
            await session.commit()


@lru_cache
def get_payment_service() -> PaymentService:
    return PaymentService(
        yookassa_client=httpx.AsyncClient(
            base_url=yookassa_settings.base_url,
            auth=httpx.BasicAuth(yookassa_settings.shop_id, yookassa_settings.secret_key)
        )
    )