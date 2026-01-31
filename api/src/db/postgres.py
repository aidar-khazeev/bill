from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from settings import pg_settings


engine = create_async_engine(
    pg_settings.get_url('psycopg'),
    pool_size=20,
    max_overflow=30,
)

session_maker = async_sessionmaker(engine)