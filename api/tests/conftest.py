import sys
import pathlib
import asyncio
import pytest
import httpx
import aiokafka
from asgi_lifespan import LifespanManager

sys.path.append(str(pathlib.Path(__file__).parent.parent/'src'))
sys.path.append(str(pathlib.Path(__file__).parent))

from settings import pg_settings, kafka_settings
from main import app


@pytest.fixture(autouse=True)
async def run_worker(run_migrations):
    from worker import run_loop
    worker_task = asyncio.create_task(run_loop())

    yield

    worker_task.cancel()

    try:
        await worker_task
    except asyncio.CancelledError:
        ...


@pytest.fixture(scope='function')
async def api_client(run_migrations):
    return httpx.AsyncClient(
        mounts={
            'http://tests': httpx.ASGITransport(app=app),
            'https://': httpx.AsyncHTTPTransport()
        },
        base_url='http://tests'
    )


@pytest.fixture(autouse=True)
async def clear_kafka_topics():
    import aiokafka.admin
    admin = aiokafka.admin.AIOKafkaAdminClient(bootstrap_servers=kafka_settings.bootstrap_servers)
    await admin.start()
    await admin.delete_topics(['payment', 'refund'])
    await admin.close()


@pytest.fixture
async def kafka_consumer():
    consumer = aiokafka.AIOKafkaConsumer('payment', 'refund', bootstrap_servers=kafka_settings.bootstrap_servers)
    await consumer.start()
    yield consumer
    await consumer.stop()


@pytest.fixture
async def yookssa_client(run_migrations):
    import services.payment
    return services.payment.get_payment_service().yookassa_client


@pytest.fixture(autouse=True)
async def run_migrations():
    from sqlalchemy import create_engine, text

    engine = create_engine(pg_settings.get_url('psycopg', db='postgres'), isolation_level='AUTOCOMMIT')
    with engine.begin() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS {pg_settings.db}'))
        conn.execute(text(f'CREATE DATABASE {pg_settings.db}'))
    engine.dispose()

    async with LifespanManager(app):
        from alembic.config import Config
        from alembic import command

        alembic_cfg = Config('alembic.ini')
        alembic_cfg.set_main_option('shut_alembic_logger', 'true')

        command.upgrade(alembic_cfg, 'head')

        yield