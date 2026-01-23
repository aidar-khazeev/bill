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
    yookassa_client: httpx.AsyncClient,
    handler_client: httpx.AsyncClient,
    kafka_producer: aiokafka.AIOKafkaProducer
):
    while True:
        await asyncio.sleep(settings.notify_refund_loop_sleep_duration)

        async with db.postgres.session_maker() as session:
            for refund, payment in (await session.execute(
                select(tables.RefundRequest, tables.Payment)
                .join(tables.Payment, tables.RefundRequest.payment_id == tables.Payment.id)
            )).tuples():
                session.expunge(refund)
                await notify_refund_handler(payment, refund, yookassa_client, handler_client, kafka_producer)


async def notify_refund_handler(
    payment: tables.Payment,
    refund_request: tables.RefundRequest,
    yookassa_client: httpx.AsyncClient,
    handler_client: httpx.AsyncClient,
    kafka_producer: aiokafka.AIOKafkaProducer
):
    if not refund_request.refunded:
        # https://yookassa.ru/developers/api#create_refund
        response = await yookassa_client.post(
            url='/v3/refunds',
            headers={'Idempotence-Key': str(payment.id)},  # !
            json={
                'payment_id': payment.external_id,
                'amount': {'value': str(payment.amount), 'currency': payment.currency}
            }
        )

        assert response.status_code == 200, response.text  # TODO
        response_json = response.json()
        assert response_json['status'] == 'succeeded', response_json['status']

        async with db.postgres.session_maker() as session:
            await session.execute(
                update(tables.RefundRequest)
                .where(tables.RefundRequest.id == refund_request.id)
                .values({tables.RefundRequest.refunded: True})
            )
            await session.commit()

    # Далее выполняется только если 'succeeded'

    if not refund_request.sent_to_topic:
        await kafka_producer.send_and_wait(
            topic='refund',
            value=json.dumps({'payment_id': str(payment.id)}).encode()
        )

        async with db.postgres.session_maker() as session:
            await session.execute(
                update(tables.RefundRequest)
                .where(tables.RefundRequest.id == refund_request.id)
                .values({tables.RefundRequest.sent_to_topic: True})
            )
            await session.delete(refund_request)
            await session.commit()

    error_msg = None
    try:
        response = await handler_client.post(
            url=refund_request.handler_url,
            json={'payment_id': str(payment.id)},
            timeout=settings.notification_timeout
        )
        if response.status_code != 200:
            error_msg = f'got status {response.status_code} from "charged" handler "{refund_request.handler_url}"'
    except httpx.ConnectError:
        error_msg = f'couldn\'t connect to "charged" handler "{refund_request.handler_url}"'

    if error_msg is not None:
        logger.warning(error_msg)
        return

    async with db.postgres.session_maker() as session:
        await session.execute(
            update(tables.Payment)
            .where(tables.Payment.id==payment.id)
            .values({tables.Payment.status: 'refunded'})
        )
        await session.delete(refund_request)
        await session.commit()