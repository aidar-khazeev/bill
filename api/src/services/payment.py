import httpx
import asyncio
from functools import lru_cache
from fastapi import Depends
from datetime import datetime
from uuid import UUID, uuid4
from decimal import Decimal
from typing import Annotated
from dataclasses import dataclass
from pydantic import BaseModel, HttpUrl
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from sqlalchemy import insert, select, update

import db.postgres
import tables
from settings import yookassa_settings



class ChargeInfo(BaseModel):
    payment_id: UUID
    confirmation_url: HttpUrl


@dataclass(frozen=True)
class PaymentService:
    session_maker: async_sessionmaker[AsyncSession]
    yookassa_client: httpx.AsyncClient

    async def charge(
        self,
        user_id: UUID,
        handler_url: str,
        return_url: str,
        amount: Decimal
    ):
        response = await self.yookassa_client.post(
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
                # Проходим 2 стадии
                # https://yookassa.ru/developers/payment-acceptance/getting-started/payment-process#capture-and-cancel
                'capture': False
            }
        )
        assert response.status_code == 200, response.text

        response_json = response.json()
        async with self.session_maker() as session:
            payment_id = uuid4()
            await session.execute(
                insert(tables.Payment).values({
                    tables.Payment.id: payment_id,
                    tables.Payment.external_id: response_json['id'],
                    tables.Payment.user_id: user_id,
                    tables.Payment.created_at: datetime.now(),
                    tables.Payment.handler_url: str(handler_url),
                    tables.Payment.amount: amount,
                    tables.Payment.status: 'created'
                })
            )
            await session.commit()

        return ChargeInfo(
            payment_id=payment_id,
            confirmation_url=HttpUrl(response_json['confirmation']['confirmation_url'])
        )

    async def run_handlers_notification_loop(self):
        handler_client = httpx.AsyncClient()

        while True:
            response = await self.yookassa_client.get(
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

                        response = await self.yookassa_client.post(
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
                        response.raise_for_status()

            async with db.postgres.get_session_maker()() as session:
                ids_and_handler_urls = (await session.execute(
                    select(tables.Payment.id, tables.Payment.handler_url)
                    .where(tables.Payment.status=='acking')
                )).all()

            tasks = (
                asyncio.create_task(self._notify_handler(handler_client, *id_and_handler_url.tuple()))
                for id_and_handler_url in ids_and_handler_urls
            )

            asyncio.gather(*tasks)

            await asyncio.sleep(8.0)


    async def _notify_handler(self, handler_client: httpx.AsyncClient, payment_id: UUID, handler_url: str):
        response = await handler_client.post(url=handler_url, json={'payment_id': str(payment_id)})
        response.raise_for_status()

        async with db.postgres.get_session_maker()() as session:
            await session.execute(
                update(tables.Payment)
                .where(tables.Payment.id==payment_id)
                .values({tables.Payment.status: 'succeeded'})
            )
            await session.commit()


@lru_cache
async def get_payment_service(
    session_maker: Annotated[async_sessionmaker[AsyncSession], Depends(db.postgres.get_session_maker)]
) -> PaymentService:
    return PaymentService(
        session_maker=session_maker,
        yookassa_client=httpx.AsyncClient(base_url='https://api.yookassa.ru')
    )