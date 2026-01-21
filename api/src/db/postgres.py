from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from settings import pg_settings


engine = create_async_engine(pg_settings.get_url('psycopg'))
session_maker = async_sessionmaker(engine)