import httpx
import asyncio
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
from sqlalchemy import insert, select, update

import db.postgres
import tables
from settings import yookassa_settings


logger = logging.getLogger('payment-service')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(name)s %(levelname)s: %(message)s'
)


class PaymentDoesntExistError(Exception):
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
        assert response.status_code == 200, response.text
        response_json = response.json()
        # При ошибке, если payment все же создался,
        # страницу для перенаправления пользователь не получит, и не подтвердит оплату.
        # Payment будет в статусе `pending`, через некоторое время перейдет в `expired_on_confirmation`
        # https://yookassa.ru/developers/payment-acceptance/getting-started/payment-process#user-confirmation

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


    async def run_handlers_notification_loop(self):
        handler_client = httpx.AsyncClient()

        while True:
            await _capture(self.yookassa_client)

            await _notify_charge(self.yookassa_client, handler_client)
            await _notify_refund(self.yookassa_client, handler_client)

            await asyncio.sleep(8.0)


async def _capture(yookassa_client: httpx.AsyncClient):
    # https://yookassa.ru/developers/api#get_payments_list
    response = await yookassa_client.get(
        url='/v3/payments',
        params={'status': 'waiting_for_capture'}
    )
    assert response.status_code == 200, response.text
    waiting = response.json()['items']

    for yoo_payment in waiting:
        metadata = yoo_payment['metadata']
        if not metadata:
            continue

        async with db.postgres.get_session_maker()() as session:
            payment = (await session.execute(
                select(tables.Payment)
                .where(tables.Payment.external_id==yoo_payment['id'])
            )).scalar_one()
            session.expunge(payment)

            await session.execute(insert(tables.ChargeRequest).values({
                tables.ChargeRequest.id: uuid4(),
                tables.ChargeRequest.payment_id: metadata['payment_id'],
                tables.ChargeRequest.handler_url: metadata['handler_url']
            }))
            await session.commit()

        response = await yookassa_client.post(
            url=f'/v3/payments/{payment.external_id}/capture',
            headers={'Idempotence-Key': str(uuid4())},
            json={'amount': {'value': str(payment.roubles), 'currency': 'RUB'}}
        )
        assert response.status_code == 200, response.text  # TODO


async def _notify_charge(yookassa_client: httpx.AsyncClient, handler_client: httpx.AsyncClient):
    async with db.postgres.get_session_maker()() as session:
        for charge in (await session.execute(select(tables.ChargeRequest))).scalars():
            session.expunge(charge)
            payment = (await session.execute(
                select(tables.Payment)
                .where(tables.Payment.id==charge.payment_id)
            )).scalar_one_or_none()

            if payment is None:
                await session.delete(charge)
                await session.commit()
                logger.warning(f'charge request {charge.id} points to non-existent payment {charge.payment_id}, ignoring')
                continue

            # https://yookassa.ru/developers/api#get_payment
            response = await yookassa_client.get(
                url=f'/v3/payments/{payment.external_id}',
                headers={'Idempotence-Key': str(uuid4())},
            )
            assert response.status_code == 200, response.text  # TODO
            response_json = response.json()

            if response_json['status'] == 'waiting_for_capture':
                # Если создание tables.ChargeRequest прошло успешно, но вызов `/capture` завершился с ошибкой,
                # то Payment может находится в статусе `waiting_for_capture`
                await session.delete(charge)
                await session.commit()
            elif response_json['status'] != 'succeeded':
                raise RuntimeError(response_json['status'])  # TODO

            # Выполняется только если 'succeeded'
            response = await handler_client.post(url=charge.handler_url, json={'payment_id': str(payment.id)})
            assert response.status_code == 200, response.text

            await session.execute(
                update(tables.Payment)
                .where(tables.Payment.id==payment.id)
                .values({tables.Payment.status: 'succeeded'})
            )
            await session.delete(charge)
            await session.commit()



async def _notify_refund(yookassa_client: httpx.AsyncClient, handler_client: httpx.AsyncClient):
    async with db.postgres.get_session_maker()() as session:
        for refund in (await session.execute(select(tables.RefundRequest))).scalars():
            payment = (await session.execute(
                select(tables.Payment)
                .where(tables.Payment.id==refund.payment_id)
            )).scalar_one_or_none()

            if payment is None:
                await session.delete(refund)
                await session.commit()
                logger.warning(f'refund request {refund.id} points to non-existent payment {refund.payment_id}, ignoring')
                continue

            # https://yookassa.ru/developers/api#create_refund
            response = await yookassa_client.post(
                url='/v3/refunds',
                headers={'Idempotence-Key': str(uuid4())},
                json={
                    'payment_id': payment.external_id,
                    'amount': {'value': str(payment.roubles), 'currency': 'RUB'}
                }
            )

            # Возврат может быть уже сделан
            if response.status_code == 400 and response.json()['code'] == 'invalid_request':
                # https://yookassa.ru/developers/api#get_refunds_list
                response = await yookassa_client.get(
                    url='/v3/refunds',
                    headers={'Idempotence-Key': str(uuid4())},
                    params={
                        'payment_id': str(payment.external_id)
                    }
                )
                assert response.status_code == 200, response.text  # TODO
                assert len(response.json()['items']) > 0
            else:
                assert response.status_code == 200, response.text  # TODO
                response_json = response.json()
                assert response_json['status'] == 'succeeded', response_json['status']

            response = await handler_client.post(url=refund.handler_url, json={'payment_id': str(payment.id)})
            assert response.status_code == 200, response.text

            await session.execute(
                update(tables.Payment)
                .where(tables.Payment.id==payment.id)
                .values({tables.Payment.status: 'refunded'})
            )
            await session.delete(refund)
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