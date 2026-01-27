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
        self,
        user_id: UUID,
        handler_url: str | None,
        return_url: str,
        amount: Decimal,
        currency: str
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
                    # https://yookassa.ru/developers/payment-acceptance/getting-started/payment-process#capture-and-cancel
                    'capture': True,
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

        async with db.postgres.session_maker() as session, session.begin():
            await session.execute(insert(tables.Payment).values({
                tables.Payment.id: payment_id,
                tables.Payment.external_id: response_json['id'],
                tables.Payment.user_id: user_id,
                tables.Payment.created_at: datetime.now(),
                tables.Payment.amount: amount,
                tables.Payment.currency: currency,
                tables.Payment.status: 'created'
            }))

        return ChargeInfo(
            payment_id=payment_id,
            confirmation_url=HttpUrl(response_json['confirmation']['confirmation_url'])
        )

    async def refund(
        self,
        payment_id: UUID,
        handler_url: str | None,
        amount: Decimal,
        currency: str
    ):
        # Мы могли бы сразу отправить post запрос на yookassa, и ответ вернуть клиенту
        # Но у yookassa после выполнения refund на своей стороне могут возникнуть проблемы при возврате ответа
        async with db.postgres.session_maker() as session, session.begin():
            payment = await session.get(tables.Payment, payment_id)
            if payment is None:
                raise PaymentDoesntExistError()

            refund_id = uuid4()

            await session.execute(insert(tables.Refund).values({
                tables.Refund.id: refund_id,
                tables.Refund.external_id: None,
                tables.Refund.payment_id: payment_id,
                tables.Refund.created_at: datetime.now(),
                tables.Refund.status: 'created',
                tables.Refund.amount: amount,
                tables.Refund.currency: currency
            }))

            await session.execute(insert(tables.RefundRequest).values({
                tables.RefundRequest.id: uuid4(),
                tables.RefundRequest.refund_id: refund_id,
                tables.RefundRequest.handler_url: handler_url
            }))


@lru_cache
def get_payment_service() -> PaymentService:
    return PaymentService(
        yookassa_client=httpx.AsyncClient(
            base_url=yookassa_settings.base_url,
            auth=httpx.BasicAuth(yookassa_settings.shop_id, yookassa_settings.secret_key),
            timeout=yookassa_settings.connection_timeout
        )
    )