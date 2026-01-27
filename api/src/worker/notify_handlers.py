import asyncio
import httpx
import logging
from sqlalchemy import select

import tables
import db.postgres
from settings import settings


logger = logging.getLogger('payment-service-handlers-notification-loop')


async def handlers_notification_loop(
    handler_client: httpx.AsyncClient
):
    while True:
        await asyncio.sleep(settings.payments_polling_loop_sleep_duration)

        async with db.postgres.session_maker() as session:
            for notification_request in (await session.execute(
                select(tables.HandlerNotificationRequest)
            )).scalars():
                session.expunge_all()
                await notify_handler(notification_request, handler_client)


async def notify_handler(
    notify_request: tables.HandlerNotificationRequest,
    handler_client: httpx.AsyncClient
):
    error_msg = None
    try:
        response = await handler_client.post(
            url=notify_request.handler_url,
            json=notify_request.data,
            timeout=settings.notification_timeout
        )
        if response.status_code != 200:
            error_msg = f'got status {response.status_code} from handler "{notify_request.handler_url}"'
    except httpx.ConnectError:
        error_msg = f'couldn\'t connect to handler "{notify_request.handler_url}"'

    if error_msg is not None:
        logger.warning(error_msg)
        return

    async with db.postgres.session_maker() as session, session.begin():
        await session.delete(notify_request)