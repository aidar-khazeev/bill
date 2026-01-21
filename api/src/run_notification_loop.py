import asyncio
import httpx
import logging
from uuid import uuid4
from sqlalchemy import select, insert, update
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession, create_async_engine

import tables
from settings import settings, yookassa_settings, pg_settings


logger = logging.getLogger('payment-service-loop')


async def run_loop():
    engine = create_async_engine(pg_settings.get_url('psycopg'))
    session_maker = async_sessionmaker(engine)

    yookassa_client = yookassa_client=httpx.AsyncClient(
        base_url='https://api.yookassa.ru',
        auth=httpx.BasicAuth(yookassa_settings.shop_id, yookassa_settings.secret_key)
    )
    handler_client = httpx.AsyncClient()

    async def capture_loop():
        while True:
            await capture_payments(session_maker, yookassa_client)
            await asyncio.sleep(settings.capture_loop_interval)

    async def notify_charge_loop():
        while True:
            await notify_charge_handlers(session_maker, yookassa_client, handler_client)
            await asyncio.sleep(settings.notify_charge_loop_interval)

    async def notify_refund_loop():
        while True:
            await notify_refund_handlers(session_maker, yookassa_client, handler_client)
            await asyncio.sleep(settings.notify_refund_loop_interval)


    await asyncio.gather(
        capture_loop(),
        notify_charge_loop(),
        notify_refund_loop()
    )


async def capture_payments(
    session_maker: async_sessionmaker[AsyncSession],
    yookassa_client: httpx.AsyncClient
):
    # https://yookassa.ru/developers/api#get_payments_list
    response = await yookassa_client.get(
        url='/v3/payments',
        params={'status': 'waiting_for_capture'}
    )
    assert response.status_code == 200, response.text
    waiting = response.json()['items']

    for yoo_payment in waiting:
        metadata = yoo_payment['metadata']
        if not metadata:
            logger.warning(f'payment {yoo_payment['id']} has no metadata, ignoring')
            continue

        payment_id = metadata['payment_id']
        handler_url = metadata['handler_url']

        async with session_maker() as session:
            payment = (await session.execute(
                select(tables.Payment)
                .where(tables.Payment.external_id==yoo_payment['id'])
            )).scalar_one()
            session.expunge(payment)

            await session.execute(insert(tables.ChargeRequest).values({
                tables.ChargeRequest.id: uuid4(),
                tables.ChargeRequest.payment_id: payment_id,
                tables.ChargeRequest.handler_url: handler_url
            }))
            await session.commit()

        response = await yookassa_client.post(
            url=f'/v3/payments/{payment.external_id}/capture',
            headers={'Idempotence-Key': str(uuid4())},
            json={'amount': {'value': str(payment.roubles), 'currency': 'RUB'}}
        )
        assert response.status_code == 200, response.text  # TODO


async def notify_charge_handlers(
    session_maker: async_sessionmaker[AsyncSession],
    yookassa_client: httpx.AsyncClient,
    handler_client: httpx.AsyncClient
):
    async with session_maker() as session:
        for charge in (await session.execute(select(tables.ChargeRequest))).scalars():
            session.expunge(charge)
            payment = (await session.execute(
                select(tables.Payment)
                .where(tables.Payment.id==charge.payment_id)
            )).scalar_one_or_none()

            if payment is None:
                logger.warning(f'charge request {charge.id} points to non-existent payment {charge.payment_id}, ignoring')
                await session.delete(charge)
                await session.commit()
                continue

            # https://yookassa.ru/developers/api#get_payment
            response = await yookassa_client.get(
                url=f'/v3/payments/{payment.external_id}',
                headers={'Idempotence-Key': str(uuid4())},
            )
            assert response.status_code == 200, response.text  # TODO
            response_json = response.json()

            if response_json['status'] == 'waiting_for_capture':
                # Если создание tables.ChargeRequest прошло успешно, но вызов `/capture` завершился с ошибкой,
                # то Payment может находится в статусе `waiting_for_capture`
                await session.delete(charge)
                await session.commit()
            elif response_json['status'] != 'succeeded':
                raise RuntimeError(response_json['status'])  # TODO

            # Далее выполняется только если 'succeeded'

            error_msg = None
            try:
                response = await handler_client.post(
                    url=charge.handler_url,
                    json={'payment_id': str(payment.id)},
                    timeout=settings.notification_timeout
                )
                if response.status_code != 200:
                    error_msg = f'got status {response.status_code} from "charged" handler "{charge.handler_url}"'
            except httpx.ConnectError:
                error_msg = f'couldn\'t connect to "charged" handler "{charge.handler_url}"'

            if error_msg is not None:
                logger.warning(error_msg)
                continue

            await session.execute(
                update(tables.Payment)
                .where(tables.Payment.id==payment.id)
                .values({tables.Payment.status: 'succeeded'})
            )
            await session.delete(charge)
            await session.commit()



async def notify_refund_handlers(
    session_maker: async_sessionmaker[AsyncSession],
    yookassa_client: httpx.AsyncClient,
    handler_client: httpx.AsyncClient
):
    async with session_maker() as session:
        for refund in (await session.execute(select(tables.RefundRequest))).scalars():
            payment = (await session.execute(
                select(tables.Payment)
                .where(tables.Payment.id==refund.payment_id)
            )).scalar_one_or_none()

            if payment is None:
                logger.warning(f'refund request {refund.id} points to non-existent payment {refund.payment_id}, ignoring')
                await session.delete(refund)
                await session.commit()
                continue

            # https://yookassa.ru/developers/api#create_refund
            response = await yookassa_client.post(
                url='/v3/refunds',
                headers={'Idempotence-Key': str(uuid4())},
                json={
                    'payment_id': payment.external_id,
                    'amount': {'value': str(payment.roubles), 'currency': 'RUB'}
                }
            )

            # Возврат может быть уже сделан
            if response.status_code == 400 and response.json()['code'] == 'invalid_request':
                # https://yookassa.ru/developers/api#get_refunds_list
                response = await yookassa_client.get(
                    url='/v3/refunds',
                    headers={'Idempotence-Key': str(uuid4())},
                    params={
                        'payment_id': str(payment.external_id)
                    }
                )
                assert response.status_code == 200, response.text  # TODO
                assert len(response.json()['items']) > 0
            else:
                assert response.status_code == 200, response.text  # TODO
                response_json = response.json()
                assert response_json['status'] == 'succeeded', response_json['status']

            error_msg = None
            try:
                response = await handler_client.post(
                    url=refund.handler_url,
                    json={'payment_id': str(payment.id)},
                    timeout=settings.notification_timeout
                )
                if response.status_code != 200:
                    error_msg = f'got status {response.status_code} from "charged" handler "{refund.handler_url}"'
            except httpx.ConnectError:
                error_msg = f'couldn\'t connect to "charged" handler "{refund.handler_url}"'

            if error_msg is not None:
                logger.warning(error_msg)
                continue

            await session.execute(
                update(tables.Payment)
                .where(tables.Payment.id==payment.id)
                .values({tables.Payment.status: 'refunded'})
            )
            await session.delete(refund)
            await session.commit()


if __name__ == '__main__':
    logging.basicConfig(level=logging.WARNING, format='%(asctime)s %(levelname)s: %(message)s')
    asyncio.run(run_loop())