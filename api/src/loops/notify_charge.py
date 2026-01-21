import asyncio
import httpx
import logging
from uuid import uuid4
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

import tables
from settings import settings


logger = logging.getLogger('payment-service-notify-charge-loop')


async def charge_handlers_notification_loop(
    session_maker: async_sessionmaker[AsyncSession],
    yookassa_client: httpx.AsyncClient,
    handler_client: httpx.AsyncClient
):
    while True:
        await asyncio.sleep(settings.notify_refund_loop_sleep_duration)

        async with session_maker() as session:
            for charge in (await session.execute(select(tables.ChargeRequest))).scalars():
                await notify_charge_handler(charge, session, yookassa_client, handler_client)


async def notify_charge_handler(
    charge: tables.ChargeRequest,
    session: AsyncSession,
    yookassa_client: httpx.AsyncClient,
    handler_client: httpx.AsyncClient
):
    session.expunge(charge)
    payment = (await session.execute(
        select(tables.Payment)
        .where(tables.Payment.id==charge.payment_id)
    )).scalar_one_or_none()

    if payment is None:
        logger.warning(f'charge request {charge.id} points to non-existent payment {charge.payment_id}, ignoring')
        await session.delete(charge)
        await session.commit()
        return

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

    # Далее выполняется только если 'succeeded'

    error_msg = None
    try:
        response = await handler_client.post(
            url=charge.handler_url,
            json={'payment_id': str(payment.id)},
            timeout=settings.notification_timeout
        )
        if response.status_code != 200:
            error_msg = f'got status {response.status_code} from "charged" handler "{charge.handler_url}"'
    except httpx.ConnectError:
        error_msg = f'couldn\'t connect to "charged" handler "{charge.handler_url}"'

    if error_msg is not None:
        logger.warning(error_msg)
        return

    await session.execute(
        update(tables.Payment)
        .where(tables.Payment.id==payment.id)
        .values({tables.Payment.status: 'succeeded'})
    )
    await session.delete(charge)
    await session.commit()