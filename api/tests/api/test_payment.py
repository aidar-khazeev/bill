import httpx
import uuid
import string
import random
import aiokafka
import asyncio
import json
import re
from pytest_httpx import HTTPXMock
from starlette import status


async def test_successful_payment(
    api_client: httpx.AsyncClient,
    yookssa_client: httpx.AsyncClient,
    kafka_consumer: aiokafka.AIOKafkaConsumer,
    httpx_mock: HTTPXMock
):
    asked_for_payment = False
    yookassa_payment_id: str | None = None
    confirmation_url: str | None = None

    async def on_payment(request: httpx.Request):
        nonlocal asked_for_payment, yookassa_payment_id, confirmation_url

        if request.method == 'POST':
            asked_for_payment = True
            yookassa_payment_id = str(uuid.uuid4())
            confirmation_url = f'https://{''.join(random.choices(string.ascii_letters, k=10))}.com'

            return httpx.Response(
                status_code=status.HTTP_200_OK,
                json={
                    'id': yookassa_payment_id,
                    'confirmation': {
                        'confirmation_url': confirmation_url
                    }
                }
            )
        elif request.method == 'GET':
            return httpx.Response(
                status_code=status.HTTP_200_OK,
                json={
                    'id': yookassa_payment_id,
                    'status': 'succeeded'
                }
            )
        else:
            raise RuntimeError(f'Unexpected method {request.method}')

    httpx_mock.add_callback(
        callback=on_payment,
        url=re.compile(r'https://api.yookassa.ru/v3/payments.*'),
        is_reusable=True
    )

    response = await api_client.post('/api/v1/payment', json={
        'user_id': str(uuid.uuid4()),
        'return_url': 'https://example.com',
        'amount': '100.00',
        'currency': 'RUB'
    })

    assert response.status_code == 200, response.text
    response_json = response.json()

    assert asked_for_payment
    assert yookassa_payment_id is not None
    assert confirmation_url is not None

    async with asyncio.timeout(20.0):
        async for msg in kafka_consumer:
            assert msg.topic == 'payment'
            assert isinstance(msg.value, bytes), msg
            value = json.loads(msg.value.decode())

            assert value == {
                'id': response_json['payment_id'],
                'status': 'succeeded',
                'extra_data': None
            }, value
            break