import httpx
import asyncio
from decimal import Decimal
from pprint import pprint
from typing import Any
from datetime import datetime
from contextlib import asynccontextmanager
from uuid import uuid4, UUID
from typing import Annotated
from pydantic import HttpUrl
from fastapi import FastAPI, Body, Depends
from fastapi.responses import ORJSONResponse
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine, AsyncSession
from sqlalchemy import select, update, insert

import db.postgres
import tables
from settings import pg_settings, yookassa_settings


yookassa_client: httpx.AsyncClient | None = None
handler_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global yookassa_client, handler_client

    db.postgres.engine = create_async_engine(pg_settings.get_url('psycopg'))
    db.postgres.session_maker = async_sessionmaker(db.postgres.engine)

    yookassa_client = httpx.AsyncClient(base_url='https://api.yookassa.ru')
    handler_client = httpx.AsyncClient()

    task = asyncio.create_task(handlers_notification_loop())

    yield

    await db.postgres.engine.dispose()
    await yookassa_client.aclose()
    await handler_client.aclose()
    task.cancel()


app = FastAPI(
    title='Bill',
    lifespan=lifespan,
    docs_url='/api/openapi',
    openapi_url='/api/openapi.json',
    default_response_class=ORJSONResponse
)


@app.post('/charge')
async def charge(
    user_id: Annotated[UUID, Body()],
    handler_url: Annotated[HttpUrl, Body()],
    amount: Annotated[Decimal, Body()],
    session_maker: Annotated[async_sessionmaker[AsyncSession], Depends(db.postgres.get_session_maker)],
    return_url: Annotated[HttpUrl, Body()] = HttpUrl('http://127.0.0.1:8000/api/openapi#/default/charge_charge_post')
) -> dict[str, Any]:
    assert yookassa_client is not None

    response = await yookassa_client.post(
        url='/v3/payments',
        headers={'Idempotence-Key': str(uuid4())},
        auth=httpx.BasicAuth(yookassa_settings.shop_id, yookassa_settings.secret_key),
        json={
            'amount': {
                'value': str(amount),
                'currency': 'RUB'
            },
            'confirmation': {
                'type': 'redirect',
                'return_url': str(return_url)
            },
            'capture': False  # Вручную, https://yookassa.ru/developers/payment-acceptance/getting-started/payment-process#capture-and-cancel
        }
    )
    assert response.status_code == 200, response.text

    response_json = response.json()
    async with session_maker() as session:
        await session.execute(
            insert(tables.Payment).values({
                tables.Payment.id: uuid4(),
                tables.Payment.external_id: response_json['id'],
                tables.Payment.user_id: user_id,
                tables.Payment.created_at: datetime.now(),
                tables.Payment.handler_url: str(handler_url),
                tables.Payment.amount: amount,
                tables.Payment.status: 'created'
            })
        )
        await session.commit()

    return response_json



async def handlers_notification_loop():
    try:
        assert yookassa_client is not None

        while True:
            response = await yookassa_client.get(
                url='/v3/payments',
                auth=httpx.BasicAuth(yookassa_settings.shop_id, yookassa_settings.secret_key),
                params={'status': 'waiting_for_capture'}
            )
            response_json = response.json()
            response.raise_for_status()

            external_ids_to_capture = [str(payment['id']) for payment in response_json['items']]

            if external_ids_to_capture:
                async with db.postgres.get_session_maker()() as session:
                    await session.execute(
                        update(tables.Payment)
                        .where(tables.Payment.external_id.in_(external_ids_to_capture))
                        .values({tables.Payment.status: 'acking'})
                    )
                    await session.commit()

                    for external_id_and_amount in (await session.execute(
                        select(tables.Payment.external_id, tables.Payment.amount)
                        .where(tables.Payment.external_id.in_(external_ids_to_capture))
                    )).fetchall():
                        external_id, amount = external_id_and_amount.tuple()

                        response = await yookassa_client.post(
                            url=f'/v3/payments/{external_id}/capture',
                            auth=httpx.BasicAuth(yookassa_settings.shop_id, yookassa_settings.secret_key),
                            headers={'Idempotence-Key': str(uuid4())},
                            json={
                                'amount': {
                                    'value': str(amount),
                                    'currency': 'RUB'
                                }
                            }
                        )
                        pprint(response.json())
                        response.raise_for_status()

            async with db.postgres.get_session_maker()() as session:
                ids_and_handler_urls = (await session.execute(
                    select(tables.Payment.id, tables.Payment.handler_url)
                    .where(tables.Payment.status=='acking')
                )).all()

            tasks = (
                asyncio.create_task(notify_handler(*id_and_handler_url.tuple()))
                for id_and_handler_url in ids_and_handler_urls
            )

            asyncio.gather(*tasks)

            await asyncio.sleep(8.0)
    except Exception as e:
        import traceback
        traceback.print_exception(e)
        raise e


async def notify_handler(payment_id: UUID, handler_url: str):
    assert handler_client is not None
    response = await handler_client.post(url=handler_url, json={'payment_id': str(payment_id)})
    response.raise_for_status()

    async with db.postgres.get_session_maker()() as session:
        await session.execute(
            update(tables.Payment)
            .where(tables.Payment.id==payment_id)
            .values({tables.Payment.status: 'succeeded'})
        )
        await session.commit()