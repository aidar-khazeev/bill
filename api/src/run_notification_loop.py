import asyncio
import httpx
import logging
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from loops.capture import payments_capture_loop
from loops.notify_charge import charge_handlers_notification_loop
from loops.notify_refund import refund_handlers_notification_loop
from settings import yookassa_settings, pg_settings


logger = logging.getLogger('payment-service-loop')


async def run_loop():
    engine = create_async_engine(pg_settings.get_url('psycopg'))
    session_maker = async_sessionmaker(engine)

    yookassa_client = yookassa_client=httpx.AsyncClient(
        base_url='https://api.yookassa.ru',
        auth=httpx.BasicAuth(yookassa_settings.shop_id, yookassa_settings.secret_key)
    )
    handler_client = httpx.AsyncClient()


    await asyncio.gather(
        payments_capture_loop(session_maker, yookassa_client),
        charge_handlers_notification_loop(session_maker, yookassa_client, handler_client),
        refund_handlers_notification_loop(session_maker, yookassa_client, handler_client)
    )


if __name__ == '__main__':
    logging.basicConfig(level=logging.WARNING, format='%(asctime)s %(levelname)s: %(message)s')
    asyncio.run(run_loop())