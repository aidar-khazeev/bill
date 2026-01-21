import logging
import httpx
import asyncio
from typing import Any
from uuid import uuid4
from sqlalchemy import select, insert
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

import tables
from settings import settings


logger = logging.getLogger('payment-service-capture-loop')


async def payments_capture_loop(
    session_maker: async_sessionmaker[AsyncSession],
    yookassa_client: httpx.AsyncClient
):
    next_cursor = None

    while True:
        await asyncio.sleep(settings.capture_loop_sleep_duration)

        # https://yookassa.ru/developers/api#get_payments_list
        response = await yookassa_client.get(
            url='/v3/payments',
            params={
                'status': 'waiting_for_capture',
                'next_cursor': next_cursor,
                'limit': 100  # max is 100
            }
        )
        assert response.status_code == 200, response.text  # TODO
        response_json = response.json()

        next_cursor = response_json.get('next_cursor', None)

        for yoo_payment in response_json['items']:
            await capture_payment(yoo_payment, session_maker, yookassa_client)


async def capture_payment(
    yoo_payment: dict[str, Any],
    session_maker: async_sessionmaker[AsyncSession],
    yookassa_client: httpx.AsyncClient
):
    metadata = yoo_payment['metadata']
    if not metadata:
        logger.warning(f'payment {yoo_payment['id']} has no metadata, ignoring')
        return

    payment_id = metadata['payment_id']
    handler_url = metadata['handler_url']

    async with session_maker() as session:
        payment = (await session.execute(
            select(tables.Payment)
            .where(tables.Payment.external_id==yoo_payment['id'])
        )).scalar_one()
        session.expunge(payment)

        await session.execute(insert(tables.ChargeRequest).values({
            tables.ChargeRequest.id: uuid4(),
            tables.ChargeRequest.payment_id: payment_id,
            tables.ChargeRequest.handler_url: handler_url
        }))
        await session.commit()

    response = await yookassa_client.post(
        url=f'/v3/payments/{payment.external_id}/capture',
        headers={'Idempotence-Key': str(uuid4())},
        json={'amount': {'value': str(payment.roubles), 'currency': 'RUB'}}
    )
    assert response.status_code == 200, response.text  # TODO