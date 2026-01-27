import asyncio
import httpx
import logging
import aiokafka

from .refund import refund_loop
from .poll_payments import payments_polling_loop
from .notify_handlers import handlers_notification_loop
from settings import yookassa_settings


async def run_loop():
    yookassa_client = yookassa_client=httpx.AsyncClient(
        base_url=yookassa_settings.base_url,
        auth=httpx.BasicAuth(yookassa_settings.shop_id, yookassa_settings.secret_key),
        timeout=yookassa_settings.connection_timeout
    )
    handler_client = httpx.AsyncClient()

    kafka_producer = aiokafka.AIOKafkaProducer(bootstrap_servers='localhost:19092')
    await kafka_producer.start()

    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(refund_loop(yookassa_client, kafka_producer))
            tg.create_task(payments_polling_loop(yookassa_client, kafka_producer))
            tg.create_task(handlers_notification_loop(handler_client))
    finally:
        await kafka_producer.stop()


if __name__ == '__main__':
    logging.basicConfig(level=logging.WARNING, format='%(asctime)s %(levelname)s: %(message)s')
    asyncio.run(run_loop())