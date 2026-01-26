import httpx
import time
from helpers import create_payment


def test_payment_list(yookassa_client: httpx.Client):
    ids = set[str]()

    for _ in range(2):
        response = create_payment(yookassa_client, roubles=100.00, auto_capture=False)
        assert response.status_code == 200, response.text
        response_json = response.json()
        ids.add(response_json['id'])

    # Ждем пока они не появятся в сипске, это происходит не сразу
    for _ in range(10):
        response = yookassa_client.get(
            url='v3/payments',
            params={'status': 'waiting_for_capture'}
        )
        assert response.status_code == 200, response.text
        response_json = response.json()
        if len(response_json['items']) == 2:
            break
        time.sleep(1.0)
    else:
        assert False

    ids_got = set[str]()

    response = yookassa_client.get(
        url='v3/payments',
        params={
            'status': 'waiting_for_capture',
            'limit': 1,
            'cursor': None  # with None cursor
        }
    )
    assert response.status_code == 200, response.text
    assert len(response.json()['items']) == 0  # we should get nothing

    response = yookassa_client.get(
        url='v3/payments',
        params={
            'status': 'waiting_for_capture',
            'limit': 1
        }
    )
    assert response.status_code == 200, response.text
    response_json = response.json()
    ids_got.add(response_json['items'][0]['id'])

    next_cursor = response_json.get('next_cursor', None)
    assert next_cursor is not None

    response = yookassa_client.get(
        url='v3/payments',
        params={
            'status': 'waiting_for_capture',
            'limit': 1,
            'cursor': next_cursor
        }
    )
    assert response.status_code == 200, response.text
    response_json = response.json()
    ids_got.add(response_json['items'][0]['id'])

    next_cursor = response_json.get('next_cursor', None)
    assert next_cursor is None

    assert ids_got == ids