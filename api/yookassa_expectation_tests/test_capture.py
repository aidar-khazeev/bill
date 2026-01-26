import httpx
from helpers import create_payment, get_payment, capture_payment


def test_capture(yookassa_client: httpx.Client):
    response = create_payment(yookassa_client, roubles=100.00, auto_capture=False)
    assert response.status_code == 200, response.text
    response_json = response.json()
    assert response_json['status'] == 'waiting_for_capture', response.text
    assert response_json['amount'] == {'value': '100.00', 'currency': 'RUB'}, response.text

    response = get_payment(yookassa_client, response_json['id'])
    assert response.status_code == 200, response.text
    response_json = response.json()
    assert response_json['status'] == 'waiting_for_capture', response.text
    assert response_json['amount'] == {'value': '100.00', 'currency': 'RUB'}, response.text

    response = capture_payment(yookassa_client, response_json['id'], 100.00)
    assert response.status_code == 200, response.text
    response_json = response.json()
    assert response_json['status'] == 'succeeded', response.text
    assert response_json['amount'] == {'value': '100.00', 'currency': 'RUB'}, response.text