import asyncio
import httpx
import logging

from loops.capture import payments_capture_loop
from loops.notify_charge import charge_handlers_notification_loop
from loops.notify_refund import refund_handlers_notification_loop
from settings import yookassa_settings


logger = logging.getLogger('payment-service-loop')


async def run_loop():
    yookassa_client = yookassa_client=httpx.AsyncClient(
        base_url=yookassa_settings.base_url,
        auth=httpx.BasicAuth(yookassa_settings.shop_id, yookassa_settings.secret_key)
    )
    handler_client = httpx.AsyncClient()


    await asyncio.gather(
        payments_capture_loop(yookassa_client),
        charge_handlers_notification_loop(yookassa_client, handler_client),
        refund_handlers_notification_loop(yookassa_client, handler_client)
    )


if __name__ == '__main__':
    logging.basicConfig(level=logging.WARNING, format='%(asctime)s %(levelname)s: %(message)s')
    asyncio.run(run_loop())