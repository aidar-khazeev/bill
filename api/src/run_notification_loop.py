import asyncio

import db.postgres
import services.payment
from asgi_lifespan import LifespanManager
from main import app


async def main():
    async with LifespanManager(app):
        payment_service = services.payment.get_payment_service(db.postgres.get_session_maker())
        await payment_service.run_handlers_notification_loop()


if __name__ == '__main__':
    asyncio.run(main())
