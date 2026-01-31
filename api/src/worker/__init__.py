import httpx
import aiokafka
import logging
import anyio

from .refund import refund_loop
from .poll_payments import payments_polling_loop
from .notify_handlers import handlers_notification_loop
from settings import yookassa_settings, kafka_settings


logger = logging.getLogger('bill-worker')


async def run():
    yookassa_client = yookassa_client=httpx.AsyncClient(
        base_url=yookassa_settings.base_url,
        auth=httpx.BasicAuth(yookassa_settings.shop_id, yookassa_settings.secret_key),
        timeout=yookassa_settings.connection_timeout_sec
    )
    handler_client = httpx.AsyncClient()

    kafka_producer = aiokafka.AIOKafkaProducer(bootstrap_servers=kafka_settings.bootstrap_servers)
    await kafka_producer.start()

    try:
        async with anyio.create_task_group() as tg:
            tg.start_soon(refund_loop, yookassa_client, kafka_producer)
            tg.start_soon(payments_polling_loop, yookassa_client, kafka_producer)
            tg.start_soon(handlers_notification_loop, handler_client)

            logger.info('worker is started')
    finally:
        await kafka_producer.stop()