from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession, AsyncEngine


engine: AsyncEngine | None = None
session_maker: async_sessionmaker[AsyncSession] | None = None


def get_engine():
    assert engine is not None
    return engine


def get_session_maker():
    assert session_maker is not None
    return session_maker


def make_session():
    return get_session_maker()()