import logging
import httpx
import asyncio
import aiokafka
import json
from typing import Any
from uuid import uuid4
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

import tables
import db.postgres
from settings import settings


logger = logging.getLogger('payment-service-payments-polling-loop')


# У нас не используется веб-хук для оповещений от Yookassa, нет доменного имени
async def payments_polling_loop(
    yookassa_client: httpx.AsyncClient,
    kafka_producer: aiokafka.AIOKafkaProducer
):
    while True:
        await asyncio.sleep(settings.payments_polling_loop_sleep_duration)

        async with db.postgres.session_maker() as session:
            for payment_request, payment in (await session.execute(
                select(tables.PaymentRequest, tables.Payment)
                .join(tables.Payment, tables.PaymentRequest.payment_id == tables.Payment.id)
            )).tuples():
                session.expunge_all()

                # https://yookassa.ru/developers/api#get_payments_list
                response = await yookassa_client.get(
                    url=f'/v3/payments/{payment.external_id}',
                )
                assert response.status_code == 200, response.text
                response_json = response.json()

                if response_json['status'] == 'pending':
                    continue

                await update_payment_status(payment_request, payment, response_json, kafka_producer)


# Использовался бы и при получении уведомлений через веб-хук
async def update_payment_status(
    payment_request: tables.PaymentRequest,
    payment: tables.Payment,
    yookassa_payment_data: dict[str, Any],
    kafka_producer: aiokafka.AIOKafkaProducer
):
    status = yookassa_payment_data['status']

    # https://yookassa.ru/developers/payment-acceptance/getting-started/payment-process#payment-statuses
    # Не должно происходить
    # 'pending' отлавливаем по стэку выше
    # 'waiting_for_capture' быть не может, так как не используем подтверждение оплаты
    if status not in ('succeeded', 'cancelled'):
        logger.warning(f'yookassa payment {yookassa_payment_data['id']} has unknown status "{status}", ignoring')
        return

    async with db.postgres.session_maker() as session, session.begin():
        await session.execute(
            update(tables.Payment)
            .values({tables.Payment.status: status})
            .where(tables.Payment.id == payment.id)
        )

    data = {
        'id': str(payment.id),
        'status': status,
        'extra_data': payment_request.extra_data
    }

    await kafka_producer.send_and_wait(
        topic='payment',
        value=json.dumps(data).encode()
    )
    logger.info(f'sent notification about payment {payment.id} to the "payment" topic')

    async with db.postgres.session_maker() as session, session.begin():
        await session.delete(payment_request)
        await session.execute(
            insert(tables.HandlerNotificationRequest)
            .values({
                tables.HandlerNotificationRequest.id: uuid4(),
                tables.HandlerNotificationRequest.handler_url: payment_request.handler_url,
                tables.HandlerNotificationRequest.data: data
            })
            .on_conflict_do_nothing()
        )