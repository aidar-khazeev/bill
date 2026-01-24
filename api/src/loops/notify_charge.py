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
    yookassa_client: httpx.AsyncClient,
    handler_client: httpx.AsyncClient,
    kafka_producer: aiokafka.AIOKafkaProducer
):
    while True:
        await asyncio.sleep(settings.notify_refund_loop_sleep_duration)

        async with db.postgres.session_maker() as session:
            for charge, payment in (await session.execute(
                select(tables.ChargeRequest, tables.Payment)
                .join(tables.Payment, tables.ChargeRequest.payment_id == tables.Payment.id)
            )).tuples():
                session.expunge(charge)
                await notify_charge_handler(payment, charge, yookassa_client, handler_client, kafka_producer)


async def notify_charge_handler(
    payment: tables.Payment,
    charge_request: tables.ChargeRequest,
    yookassa_client: httpx.AsyncClient,
    handler_client: httpx.AsyncClient,
    kafka_producer: aiokafka.AIOKafkaProducer
):
    # if not charge_request.captured:
    #     # https://yookassa.ru/developers/api#capture_payment
    #     response = await yookassa_client.post(
    #         url=f'/v3/payments/{payment.external_id}/capture',
    #         headers={'Idempotence-Key': str(payment.id)},  # !
    #         json={'amount': {'value': str(payment.amount), 'currency': payment.currency}}
    #     )
    #     assert response.status_code == 200, response.text  # TODO
    #     response_json = response.json()

    #     if response_json['status'] != 'succeeded':
    #         raise RuntimeError(response_json['status'])  # TODO

    #     async with db.postgres.session_maker() as session:
    #         await session.execute(
    #             update(tables.ChargeRequest)
    #             .where(tables.ChargeRequest.id == charge_request.id)
    #             .values({tables.ChargeRequest.captured: True})
    #         )
    #         await session.commit()

    # Далее выполняется только если 'succeeded'

    if not charge_request.sent_to_topic:
        await kafka_producer.send_and_wait(
            topic='charge',
            value=json.dumps({'payment_id': str(payment.id)}).encode()
        )

        async with db.postgres.session_maker() as session:
            await session.execute(
                update(tables.ChargeRequest)
                .where(tables.ChargeRequest.id == charge_request.id)
                .values({tables.ChargeRequest.sent_to_topic: True})
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