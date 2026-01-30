import asyncio
import httpx
import logging
from datetime import datetime, timedelta
from sqlalchemy import select, update, nulls_last, or_

import tables
import db.postgres
from settings import settings


logger = logging.getLogger('bill-worker-handlers-notification-loop')


async def handlers_notification_loop(
    handler_client: httpx.AsyncClient
):
    while True:
        async with db.postgres.session_maker() as session:
            request = await session.scalar(
                select(tables.HandlerNotificationRequest)
                .where(or_(
                    tables.HandlerNotificationRequest.processed_at.is_(None),
                    tables.HandlerNotificationRequest.processed_at < (datetime.now() - timedelta(seconds=settings.handlers_notification_loop_sleep_duration))
                ))
                .order_by(nulls_last(tables.HandlerNotificationRequest.processed_at.asc()))
                .with_for_update(skip_locked=True)
                .limit(1)
            )

            if request:
                session.expunge(request)
                if await notify_handler(request, handler_client):
                    await session.delete(request)
                else:
                    await session.execute(
                        update(tables.HandlerNotificationRequest.processed_at)
                        .where(tables.HandlerNotificationRequest.id == request.id)
                        .values({tables.HandlerNotificationRequest.processed_at: datetime.now()})
                    )

                await session.commit()
                continue

        await asyncio.sleep(settings.handlers_notification_loop_sleep_duration)


async def notify_handler(
    notify_request: tables.HandlerNotificationRequest,
    handler_client: httpx.AsyncClient
) -> bool:
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
        return False

    return True