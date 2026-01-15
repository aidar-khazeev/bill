from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import db.postgres
import api.v1.payment
from settings import pg_settings



@asynccontextmanager
async def lifespan(app: FastAPI):
    db.postgres.engine = create_async_engine(pg_settings.get_url('psycopg'))
    db.postgres.session_maker = async_sessionmaker(db.postgres.engine)

    yield

    await db.postgres.engine.dispose()


app = FastAPI(
    title='Bill',
    lifespan=lifespan,
    docs_url='/api/openapi',
    openapi_url='/api/openapi.json',
    default_response_class=ORJSONResponse
)


app.include_router(api.v1.payment.router, prefix='/api/v1/pay', tags=['Payment'])
