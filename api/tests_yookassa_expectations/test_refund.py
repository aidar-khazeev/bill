import httpx
import pytest
from uuid import uuid4

from helpers import create_payment, create_refund


@pytest.mark.parametrize(
    'refund_roubles', ('100.00', '50.00', '200.00')
)
def test_refund(
    yookassa_client: httpx.Client,
    refund_roubles: str
):
    response = create_payment(yookassa_client, roubles=100.00)
    assert response.status_code == 200, response.text
    response_json = response.json()

    assert response_json['status'] == 'succeeded', response.text
    payment_id = response_json['id']

    response = create_refund(yookassa_client, payment_id, refund_roubles)
    response_json = response.json()

    if float(refund_roubles) <= 100.00:
        assert response.status_code == 200, response.text

        assert response_json['status'] == 'succeeded', response.text
        assert response_json['payment_id'] == payment_id
        assert response_json['amount'] == {
            'value': refund_roubles,
            'currency': 'RUB'
        }, response.text

    else:
        assert response.status_code == 400, response.text
        assert response_json['type'] == 'error'
        assert response_json['parameter'] == 'amount.value'
        assert response_json['code'] == 'invalid_request'


def test_double_refund(yookassa_client: httpx.Client):
    response = create_payment(yookassa_client, roubles=100.00)
    assert response.status_code == 200, response.text
    response_json = response.json()

    assert response_json['status'] == 'succeeded', response.text
    payment_id = response_json['id']

    idempotence_key = str(uuid4())

    response = create_refund(yookassa_client, id=payment_id, roubles=100.0, idempotence_key=idempotence_key)
    assert response.status_code == 200, response.text

    # Same idempotence key
    response = create_refund(yookassa_client, id=payment_id, roubles=100.0, idempotence_key=idempotence_key)
    assert response.status_code == 200, response.text

    # Other idempotence key
    response = create_refund(yookassa_client, id=payment_id, roubles=100.0, idempotence_key=str(uuid4()))
    response_json = response.json()
    assert response.status_code == 400, response.text
    assert response_json['type'] == 'error'
    assert response_json['parameter'] == 'amount.value'
    assert response_json['code'] == 'invalid_request'


def test_double_refund_multiple_partial(yookassa_client: httpx.Client):
    response = create_payment(yookassa_client, roubles=100.00)
    assert response.status_code == 200, response.text
    response_json = response.json()

    assert response_json['status'] == 'succeeded', response.text
    payment_id = response_json['id']

    response = create_refund(yookassa_client, id=payment_id, roubles=10.0)
    assert response.status_code == 200, response.text

    response = create_refund(yookassa_client, id=payment_id, roubles=10.0)
    assert response.status_code == 200, response.text

    response = create_refund(yookassa_client, id=payment_id, roubles=80.0)
    assert response.status_code == 200, response.text

    response = create_refund(yookassa_client, id=payment_id, roubles=10.0)
    assert response.status_code == 400, response.text