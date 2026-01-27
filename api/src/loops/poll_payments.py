import logging
import httpx
import asyncio
from typing import Any
from uuid import uuid4
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

import tables
import db.postgres
from settings import settings


logger = logging.getLogger('payment-service-status-fetch-loop')


# У нас не используется веб-хук для оповещений от Yookassa, нет доменного имени
async def payments_status_polling_loop(yookassa_client: httpx.AsyncClient):
    while True:
        await asyncio.sleep(settings.payments_polling_loop_sleep_duration)

        async with db.postgres.session_maker() as session:
            for payment in (await session.execute(
                select(tables.Payment)
                .where(tables.Payment.status == 'created')
            )).scalars():
                session.expunge(payment)

                # https://yookassa.ru/developers/api#get_payments_list
                response = await yookassa_client.get(
                    url=f'/v3/payments/{payment.external_id}',
                )
                assert response.status_code == 200, response.text
                response_json = response.json()

                if response_json['status'] == 'pending':
                    continue

                await update_payment_status(yookassa_payment_data=response_json)


# Использовался бы и при получении уведомлений через веб-хук
async def update_payment_status(yookassa_payment_data: dict[str, Any]):
    metadata = yookassa_payment_data['metadata']
    if not metadata:  # Все оплаты созданные сервисом указывают metadata
        logger.warning(f'yookassa payment {yookassa_payment_data['id']} has no metadata, ignoring')
        return

    status = yookassa_payment_data['status']

    # https://yookassa.ru/developers/payment-acceptance/getting-started/payment-process#payment-statuses
    # Не должно происходить
    # 'pending' отлавливаем по стэку выше
    # 'waiting_for_capture' быть не может, так как не используем подтверждение оплаты
    if status not in ('succeeded', 'cancelled'):
        logger.warning(f'yookassa payment {yookassa_payment_data['id']} has unknown status "{status}", ignoring')
        return

    payment_id = metadata['payment_id']
    handler_url = metadata.get('handler_url', None)

    async with db.postgres.session_maker() as session, session.begin():
        await session.execute(
            update(tables.Payment)
            .values({tables.Payment.status: status})
            .where(tables.Payment.id == payment_id)
        )
        await session.execute(insert(tables.ChargeNotificationRequest).values({
            tables.ChargeNotificationRequest.id: uuid4(),
            tables.ChargeNotificationRequest.payment_id: payment_id,
            tables.ChargeNotificationRequest.handler_url: handler_url
        }).on_conflict_do_nothing())