import logging
import httpx
import asyncio
import aiokafka
import json
import anyio
from uuid import uuid4
from datetime import datetime, timedelta
from sqlalchemy import select, update, nulls_last, or_
from sqlalchemy.dialects.postgresql import insert

import tables
import db.postgres
from settings import settings


logger = logging.getLogger('bill-worker-payments-polling-loop')


# У нас не используется веб-хук для оповещений от Yookassa, нет доменного имени
async def payments_polling_loop(yookassa_client: httpx.AsyncClient, kafka_producer: aiokafka.AIOKafkaProducer):
    limiter = anyio.CapacityLimiter(settings.payments_polling_loop_concurrency)

    async def check_for_payment():
        async with limiter:
            print("polling")
            async with db.postgres.session_maker() as session:
                request = await session.scalar(
                    select(tables.PaymentRequest)
                    .where(or_(
                        tables.PaymentRequest.processed_at.is_(None),
                        tables.PaymentRequest.processed_at < (datetime.now() - timedelta(seconds=settings.payments_polling_loop_sleep_duration))
                    ))
                    .order_by(nulls_last(tables.PaymentRequest.processed_at.asc()))
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )

                if request:
                    if await update_payment_status(request, yookassa_client, kafka_producer):
                        await session.delete(request)
                    else:
                        await session.execute(
                            update(tables.PaymentRequest)
                            .where(tables.PaymentRequest.id == request.id)
                            .values({tables.PaymentRequest.processed_at: datetime.now()})
                        )

                    await session.commit()
                    return

            await asyncio.sleep(settings.payments_polling_loop_sleep_duration)

    async with anyio.create_task_group() as tg:
        while True:
            async with limiter:
                tg.start_soon(check_for_payment)
            await asyncio.sleep(0)


# Использовался бы и при получении уведомлений через веб-хук
async def update_payment_status(
    payment_request: tables.PaymentRequest,
    yookassa_client: httpx.AsyncClient,
    kafka_producer: aiokafka.AIOKafkaProducer
) -> bool:
    async with db.postgres.session_maker() as session:
        payment = (await session.execute(
            select(tables.Payment)
            .where(tables.Payment.id == payment_request.payment_id)
        )).scalar_one()

    # https://yookassa.ru/developers/api#get_payments_list
    response = await yookassa_client.get(
        url=f'/v3/payments/{payment.external_id}',
    )
    assert response.status_code == 200, response.text
    yookassa_payment_data = response.json()

    if yookassa_payment_data['status'] == 'pending':
        return False

    status = yookassa_payment_data['status']

    # https://yookassa.ru/developers/payment-acceptance/getting-started/payment-process#payment-statuses
    # Не должно происходить
    # 'pending' отлавливаем по стэку выше
    # 'waiting_for_capture' быть не может, так как не используем подтверждение оплаты
    if status not in ('succeeded', 'canceled'):
        logger.warning(f'yookassa payment {yookassa_payment_data['id']} has unknown status "{status}", ignoring')
        return False

    if status == 'canceled':  # Оба варианта верны. Yookassa использует `canceled`, мы - `cancelled`
        status = 'cancelled'

    async with db.postgres.session_maker() as session, session.begin():
        cancellation_details = yookassa_payment_data.get('cancellation_details')
        cancellation_reason = cancellation_details['reason'] if cancellation_details else None

        await session.execute(
            update(tables.Payment)
            .values({
                tables.Payment.status: status,
                tables.Payment.external_cancellation_reason: cancellation_reason
            })
            .where(tables.Payment.id == payment.id)
        )

    data = {
        'id': str(payment.id),
        'status': status,
        'extra_data': payment_request.extra_data
    }

    # TODO Использовать Transactional Producer? https://aiokafka.readthedocs.io/en/stable/producer.html#transactional-producer
    await kafka_producer.send_and_wait(
        topic='payment',
        value=json.dumps(data).encode()
    )
    logger.info(f'sent notification about payment {payment.id} to the "payment" topic')

    if payment_request.handler_url:
        async with db.postgres.session_maker() as session, session.begin():
            await session.execute(
                insert(tables.HandlerNotificationRequest)
                .values({
                    tables.HandlerNotificationRequest.id: uuid4(),
                    tables.HandlerNotificationRequest.created_at: datetime.now(),
                    tables.HandlerNotificationRequest.handler_url: payment_request.handler_url,
                    tables.HandlerNotificationRequest.data: data
                })
                .on_conflict_do_nothing()
            )

    return True