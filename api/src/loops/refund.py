import logging
import httpx
import asyncio
from uuid import uuid4
from sqlalchemy import select, update, insert

import tables
import db.postgres
from settings import settings


logger = logging.getLogger('payment-service-status-fetch-loop')


async def refund_loop(yookassa_client: httpx.AsyncClient):
    while True:
        await asyncio.sleep(settings.refund_loop_sleep_duration)

        async with db.postgres.session_maker() as session:
            for refund_request, refund, payment in (await session.execute(
                select(tables.RefundRequest, tables.Refund, tables.Payment)
                .join(tables.Refund, tables.RefundRequest.refund_id == tables.Refund.id)
                .join(tables.Payment, tables.Refund.payment_id == tables.Payment.id)
            )).tuples():
                session.expunge_all()
                await refund_payment(refund_request, refund, payment, yookassa_client)


async def refund_payment(
    refund_request: tables.RefundRequest,
    refund: tables.Refund,
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
        await session.delete(refund_request)
        await session.execute(
            update(tables.Refund)
            .where(tables.Refund.id == refund.id)
            .values({
                tables.Refund.external_id: response_json['id'],
                tables.Refund.status: status,
                tables.Refund.external_cancellation_reason: cancellation_reason
            })
        )
        await session.execute(
            insert(tables.RefundNotificationRequest)
            .values({
                tables.RefundNotificationRequest.id: uuid4(),
                tables.RefundNotificationRequest.refund_id: refund.id,
                tables.RefundNotificationRequest.handler_url: refund_request.handler_url
            })
        )