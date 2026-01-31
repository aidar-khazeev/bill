import httpx
import uuid
import aiokafka
import asyncio
import json


async def test_successful_refund(
    api_client: httpx.AsyncClient,
    kafka_consumer: aiokafka.AIOKafkaConsumer,
):
    response = await api_client.post('/api/v1/payment', json={
        'user_id': str(uuid.uuid4()),
        'return_url': 'https://example.com',
        'amount': '100.00',
        'currency': 'RUB',
        'card_data': {
            # https://yookassa.ru/developers/payment-acceptance/testing-and-going-live/testing#test-bank-card
            'number': '5555555555554444',  # без подтверждения
            'expiry_year': '2030',
            'expiry_month': '12',
            'cardholder': 'XXX',
            'csc': '543'
        }
    })

    assert response.status_code == 200, response.text
    response_json = response.json()
    payment_id = response_json['payment_id']

    async with asyncio.timeout(20.0):
        async for msg in kafka_consumer:
            assert msg.topic == 'payment'
            assert isinstance(msg.value, bytes), msg
            break


    response = await api_client.post(f'/api/v1/payment/{payment_id}/refund', json={
        'user_id': str(uuid.uuid4()),
        'amount': '100.00',
        'currency': 'RUB',
        'extra_data': {
            'refund_test': '😎'
        }
    })
    assert response.status_code == 200, response.text
    response_json = response.json()

    async with asyncio.timeout(20.0):
        async for msg in kafka_consumer:
            assert msg.topic == 'refund'
            assert isinstance(msg.value, bytes), msg

            value = json.loads(msg.value)
            assert isinstance(value, dict)

            value.pop('id')
            assert value == {
                'status': 'succeeded',
                'external_cancellation_reason': None,
                'extra_data': {
                    'refund_test': '😎'
                }
            }, value
            break