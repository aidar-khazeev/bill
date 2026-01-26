import asyncio
import httpx
import logging
import aiokafka
import json
from sqlalchemy import select, update

import tables
import db.postgres
from settings import settings


logger = logging.getLogger('payment-service-notify-charge-loop')


async def charge_handlers_notification_loop(
    handler_client: httpx.AsyncClient,
    kafka_producer: aiokafka.AIOKafkaProducer
):
    while True:
        await asyncio.sleep(settings.payments_polling_loop_sleep_duration)

        async with db.postgres.session_maker() as session:
            for notification_request, payment in (await session.execute(
                select(tables.ChargeNotificationRequest, tables.Payment)
                .join(tables.Payment, tables.ChargeNotificationRequest.payment_id == tables.Payment.id)
            )).tuples():
                session.expunge_all()
                await notify_charge_handler(payment, notification_request, handler_client, kafka_producer)


async def notify_charge_handler(
    payment: tables.Payment,
    charge_request: tables.ChargeNotificationRequest,
    handler_client: httpx.AsyncClient,
    kafka_producer: aiokafka.AIOKafkaProducer
):
    if not charge_request.sent_to_topic:
        # Может быть отправлено несколько раз, консьюмер должен быть идемпотентным
        await kafka_producer.send_and_wait(
            topic='charge',
            value=json.dumps({'payment_id': str(payment.id)}).encode()
        )
        async with db.postgres.session_maker() as session:
            await session.execute(
                update(tables.ChargeNotificationRequest)
                .where(tables.ChargeNotificationRequest.id == charge_request.id)
                .values({tables.ChargeNotificationRequest.sent_to_topic: True})
            )

    error_msg = None
    try:
        response = await handler_client.post(
            url=charge_request.handler_url,
            json={'payment_id': str(payment.id)},
            timeout=settings.notification_timeout
        )
        if response.status_code != 200:
            error_msg = f'got status {response.status_code} from "charged" handler "{charge_request.handler_url}"'
    except httpx.ConnectError:
        error_msg = f'couldn\'t connect to "charged" handler "{charge_request.handler_url}"'

    if error_msg is not None:
        logger.warning(error_msg)
        return

    async with db.postgres.session_maker() as session:
        await session.execute(
            update(tables.Payment)
            .where(tables.Payment.id == payment.id)
            .values({tables.Payment.status: 'succeeded'})
        )
        await session.delete(charge_request)
        await session.commit()