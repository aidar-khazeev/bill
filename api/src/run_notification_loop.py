import asyncio
import httpx
import logging
import aiokafka

from loops.refund import refund_loop
from loops.poll_payments import payments_status_polling_loop
from loops.notify_charge import charge_handlers_notification_loop
from loops.notify_refund import refund_handlers_notification_loop
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
        await asyncio.gather(
            refund_loop(yookassa_client),
            payments_status_polling_loop(yookassa_client),
            charge_handlers_notification_loop(handler_client, kafka_producer),
            refund_handlers_notification_loop(handler_client, kafka_producer)
        )
    finally:
        await kafka_producer.stop()


if __name__ == '__main__':
    logging.basicConfig(level=logging.WARNING, format='%(asctime)s %(levelname)s: %(message)s')
    asyncio.run(run_loop())