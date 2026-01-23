import httpx
from helpers import create_payment


def test_payment(yookassa_client: httpx.Client):
    response = create_payment(yookassa_client, roubles=100.00)
    assert response.status_code == 200, response.text
    response_json = response.json()

    assert response_json['status'] == 'succeeded', response.text
    assert response_json['amount'] == {
        'value': '100.00',
        'currency': 'RUB'
    }, response.text