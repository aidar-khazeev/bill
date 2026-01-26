import httpx
import asyncio
import logging
import aiokafka
import json
from sqlalchemy import select, update

import tables
import db.postgres
from settings import settings


logger = logging.getLogger('payment-service-notify-refund-loop')


async def refund_handlers_notification_loop(
    handler_client: httpx.AsyncClient,
    kafka_producer: aiokafka.AIOKafkaProducer
):
    while True:
        await asyncio.sleep(settings.payments_polling_loop_sleep_duration)

        async with db.postgres.session_maker() as session:
            for refund_request, refund in (await session.execute(
                select(tables.RefundNotificationRequest, tables.Refund)
                .join(tables.Refund, tables.RefundNotificationRequest.refund_id == tables.Refund.id)
            )).tuples():
                session.expunge_all()
                await notify_refund_handler(refund_request, refund, handler_client, kafka_producer)


async def notify_refund_handler(
    notify_request: tables.RefundNotificationRequest,
    refund: tables.Refund,
    handler_client: httpx.AsyncClient,
    kafka_producer: aiokafka.AIOKafkaProducer
):
    if not notify_request.sent_to_topic:
        await kafka_producer.send_and_wait(
            topic='refund',
            value=json.dumps({'refund_id': str(refund.id)}).encode()
        )
        logger.info(f'sent notification about refund {refund.id} to the "refund" topic')
        async with db.postgres.session_maker() as session:
            await session.execute(
                update(tables.RefundNotificationRequest)
                .where(tables.RefundNotificationRequest.id == notify_request.id)
                .values({tables.RefundNotificationRequest.sent_to_topic: True})
            )

    if notify_request.handler_url:
        error_msg = None
        try:
            response = await handler_client.post(
                url=notify_request.handler_url,
                json={'refund_id': str(refund.id)},
                timeout=settings.notification_timeout
            )
            if response.status_code != 200:
                error_msg = f'got status {response.status_code} from "charged" handler "{notify_request.handler_url}"'
        except httpx.ConnectError:
            error_msg = f'couldn\'t connect to "charged" handler "{notify_request.handler_url}"'

    if error_msg is not None:
        logger.warning(error_msg)
        return

    async with db.postgres.session_maker() as session:
        await session.delete(notify_request)
        await session.commit()