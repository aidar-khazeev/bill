from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

import db.postgres
import api.v1.payment
import services.payment



@asynccontextmanager
async def lifespan(app: FastAPI):
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


@app.exception_handler(services.payment.PaymentDoesntExistError)
async def on_payment_doesnt_exist_error(request, exc):
    return ORJSONResponse(
        status_code=401,
        content={'message': 'payment with such id doesn\'t exist'}
    )


@app.exception_handler(services.payment.ExternalPaymentServiceError)
async def on_external_payment_service_error(request, exc):
    return ORJSONResponse(
        status_code=500,
        content={'message': 'external payment service error'}
    )