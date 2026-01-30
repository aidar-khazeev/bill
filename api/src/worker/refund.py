import logging
import httpx
import asyncio
import json
import aiokafka
from uuid import uuid4
from datetime import datetime, timedelta
from sqlalchemy import select, update, nulls_last, or_
from sqlalchemy.dialects.postgresql import insert

import tables
import db.postgres
from settings import settings


logger = logging.getLogger('bill-worker-refund-loop')


async def refund_loop(yookassa_client: httpx.AsyncClient, kafka_producer: aiokafka.AIOKafkaProducer):
    while True:
        async with db.postgres.session_maker() as session:
            request = await session.scalar(
                select(tables.RefundRequest)
                .where(or_(
                    tables.RefundRequest.processed_at.is_(None),
                    tables.RefundRequest.processed_at < (datetime.now() - timedelta(seconds=settings.refund_loop_sleep_duration))
                ))
                .order_by(nulls_last(tables.RefundRequest.processed_at.asc()))
                .with_for_update(skip_locked=True)
                .limit(1)
            )

            if request:
                session.expunge(request)
                if await refund_payment(request, kafka_producer, yookassa_client):
                    await session.delete(request)
                else:
                    await session.execute(
                        update(tables.RefundRequest)
                        .where(tables.RefundRequest.id == request.id)
                        .values({tables.RefundRequest.processed_at: datetime.now()})
                    )

                await session.commit()
                continue

        await asyncio.sleep(settings.refund_loop_sleep_duration)


async def refund_payment(
    refund_request: tables.RefundRequest,
    kafka_producer: aiokafka.AIOKafkaProducer,
    yookassa_client: httpx.AsyncClient
) -> bool:
    async with db.postgres.session_maker() as session:
        refund = (await session.execute(
            select(tables.Refund)
            .where(tables.Refund.id == refund_request.refund_id)
        )).scalar_one()
        payment = (await session.execute(
            select(tables.Payment)
            .where(tables.Payment.id == refund.payment_id)
        )).scalar_one()

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
        return False

    # https://yookassa.ru/developers/api#refund_object_status
    # Не должно быть других статусов, проверяем на всякий случай
    if status not in ('succeeded', 'cancelled'):
        logger.warning(f'yookassa refund {response_json['id']} has unknown status "{status}", ignoring')
        return False

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
        'external_cancellation_reason': cancellation_reason,
        'extra_data': refund_request.extra_data
    }

    await kafka_producer.send_and_wait(
        topic='refund',
        value=json.dumps(data).encode()
    )
    logger.info(f'sent notification about refund {refund.id} to the "refund" topic')

    if refund_request.handler_url:
        async with db.postgres.session_maker() as session, session.begin():
            await session.execute(
                insert(tables.HandlerNotificationRequest)
                .values({
                    tables.HandlerNotificationRequest.id: uuid4(),
                    tables.HandlerNotificationRequest.created_at: datetime.now(),
                    tables.HandlerNotificationRequest.handler_url: refund_request.handler_url,
                    tables.HandlerNotificationRequest.data: data
                })
                .on_conflict_do_nothing()
            )

    return True