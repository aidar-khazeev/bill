import logging
import httpx
import asyncio
import json
import aiokafka
from uuid import uuid4
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

import tables
import db.postgres
from settings import settings


logger = logging.getLogger('payment-service-status-fetch-loop')


async def refund_loop(yookassa_client: httpx.AsyncClient, kafka_producer: aiokafka.AIOKafkaProducer):
    while True:
        await asyncio.sleep(settings.refund_loop_sleep_duration)

        async with db.postgres.session_maker() as session:
            for refund_request, refund, payment in (await session.execute(
                select(tables.RefundRequest, tables.Refund, tables.Payment)
                .join(tables.Refund, tables.RefundRequest.refund_id == tables.Refund.id)
                .join(tables.Payment, tables.Refund.payment_id == tables.Payment.id)
            )).tuples():
                session.expunge_all()
                await refund_payment(refund_request, refund, kafka_producer, payment, yookassa_client)


async def refund_payment(
    refund_request: tables.RefundRequest,
    refund: tables.Refund,
    kafka_producer: aiokafka.AIOKafkaProducer,
    payment: tables.Payment,
    yookassa_client: httpx.AsyncClient
):
    # https://yookassa.ru/developers/api#create_refund
    response = await yookassa_client.post(
        url='/v3/refunds',
        headers={'Idempotence-Key': str(refund_request.id)},  # !
        json={
            'payment_id': payment.external_id,
            'amount': {'value': str(refund.amount), 'currency': refund.currency},
            'metadata': {
                'refund_id': str(refund.id)
            }
        }
    )

    response_json = response.json()

    if response.status_code == 200:
        status = response_json['status']
        cancellation_details = response_json.get('cancellation_details')
        cancellation_reason = cancellation_details['reason'] if cancellation_details else None
    elif response.status_code == 400:
        status = 'cancelled'
        cancellation_reason = response_json['description']
    else:
        logger.warning(f'unexpected http status from "refund": {response.status_code}, ignoring')
        return

    # https://yookassa.ru/developers/api#refund_object_status
    # Не должно быть других статусов, проверяем на всякий случай
    if status not in ('succeeded', 'cancelled'):
        logger.warning(f'yookassa refund {response_json['id']} has unknown status "{status}", ignoring')
        return

    async with db.postgres.session_maker() as session, session.begin():
        await session.execute(
            update(tables.Refund)
            .where(tables.Refund.id == refund.id)
            .values({
                tables.Refund.external_id: response_json['id'],
                tables.Refund.status: status,
                tables.Refund.external_cancellation_reason: cancellation_reason
            })
        )

    data = {
        'id': str(refund.id),
        'status': status,
        'external_cancellation_reason': cancellation_reason
    }

    await kafka_producer.send_and_wait(
        topic='refund',
        value=json.dumps(data).encode()
    )
    logger.info(f'sent notification about refund {refund.id} to the "refund" topic')

    async with db.postgres.session_maker() as session, session.begin():
        await session.delete(refund_request)
        await session.execute(
            insert(tables.HandlerNotificationRequest)
            .values({
                tables.HandlerNotificationRequest.id: uuid4(),
                tables.HandlerNotificationRequest.handler_url: refund_request.handler_url,
                tables.HandlerNotificationRequest.data: data
            })
            .on_conflict_do_nothing()
        )