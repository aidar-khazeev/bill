import logging
import httpx
import asyncio
from uuid import uuid4
from sqlalchemy import select, update, insert, delete

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

    assert response.status_code == 200, response.text  # TODO
    response_json = response.json()
    assert response_json['status'] == 'succeeded', response_json['status']

    async with db.postgres.session_maker() as session, session.begin():
        await session.execute(
            update(tables.Refund)
            .where(tables.Refund.id == refund.id)
            .values({tables.Refund.external_id: response_json['id']})
        )
        await session.execute(
            insert(tables.RefundNotificationRequest)
            .values({
                tables.RefundNotificationRequest.id: uuid4(),
                tables.RefundNotificationRequest.refund_id: refund.id,
                tables.RefundNotificationRequest.handler_url: refund_request.handler_url
            })
        )
        await session.execute(
            delete(tables.RefundRequest)
            .where(tables.RefundRequest.id == refund_request.id)
        )