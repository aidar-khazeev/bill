import logging
import httpx
import asyncio
from uuid import uuid4
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

import tables
import db.postgres
from settings import settings


logger = logging.getLogger('payment-service-status-fetch-loop')


async def payments_status_polling_loop(yookassa_client: httpx.AsyncClient):
    while True:
        await asyncio.sleep(settings.notify_refund_loop_sleep_duration)

        async with db.postgres.session_maker() as session:
            for payment in (await session.execute(
                select(tables.Payment)
                .where(tables.Payment.status == 'created')
            )).scalars():
                session.expunge_all()
                await fetch_payment_status(yookassa_client, payment)


async def fetch_payment_status(yookassa_client: httpx.AsyncClient, payment: tables.Payment):

    response = await yookassa_client.get(
        url=f'/v3/payments/{payment.external_id}',
    )
    assert response.status_code == 200, response.text
    response_json = response.json()

    if response_json['status'] == 'pending':
        return

    metadata = response_json['metadata']
    if not metadata:
        logger.warning(f'payment {response_json['id']} has no metadata, ignoring')
        return

    payment_id = metadata['payment_id']
    handler_url = metadata['handler_url']

    async with db.postgres.session_maker() as session:
        await session.execute(update(tables.Payment).values({
            tables.Payment.status: (
                'succeeded' if response_json['status'] == 'succeeded' else
                'cancelled'
            )
        }))

        await session.execute(insert(tables.ChargeRequest).values({
            tables.ChargeRequest.id: uuid4(),
            tables.ChargeRequest.payment_id: payment_id,
            tables.ChargeRequest.handler_url: handler_url
        }).on_conflict_do_nothing())

        await session.commit()