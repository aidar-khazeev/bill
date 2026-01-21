import httpx
import asyncio
import logging
from uuid import uuid4
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

import tables
from settings import settings


logger = logging.getLogger('payment-service-refund-charge-loop')


async def refund_handlers_notification_loop(
    session_maker: async_sessionmaker[AsyncSession],
    yookassa_client: httpx.AsyncClient,
    handler_client: httpx.AsyncClient
):
    while True:
        await asyncio.sleep(settings.notify_refund_loop_sleep_duration)

        async with session_maker() as session:
            for refund in (await session.execute(select(tables.RefundRequest))).scalars():
                await notify_refund_handler(refund, session, yookassa_client, handler_client)


async def notify_refund_handler(
    refund: tables.RefundRequest,
    session: AsyncSession,
    yookassa_client: httpx.AsyncClient,
    handler_client: httpx.AsyncClient
):

    payment = (await session.execute(
        select(tables.Payment)
        .where(tables.Payment.id==refund.payment_id)
    )).scalar_one_or_none()

    if payment is None:
        logger.warning(f'refund request {refund.id} points to non-existent payment {refund.payment_id}, ignoring')
        await session.delete(refund)
        await session.commit()
        return

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

    error_msg = None
    try:
        response = await handler_client.post(
            url=refund.handler_url,
            json={'payment_id': str(payment.id)},
            timeout=settings.notification_timeout
        )
        if response.status_code != 200:
            error_msg = f'got status {response.status_code} from "charged" handler "{refund.handler_url}"'
    except httpx.ConnectError:
        error_msg = f'couldn\'t connect to "charged" handler "{refund.handler_url}"'

    if error_msg is not None:
        logger.warning(error_msg)
        return

    await session.execute(
        update(tables.Payment)
        .where(tables.Payment.id==payment.id)
        .values({tables.Payment.status: 'refunded'})
    )
    await session.delete(refund)
    await session.commit()