import sys
import pytest
import pathlib
import httpx
from uuid import uuid4

sys.path.append(str(pathlib.Path(__file__).parent.parent.parent/'src'))
sys.path.append(str(pathlib.Path(__file__).parent.parent))


@pytest.fixture
def yookassa_client():
    from settings import yookassa_settings
    return httpx.Client(
        base_url=yookassa_settings.base_url,
        auth=httpx.BasicAuth(yookassa_settings.shop_id, yookassa_settings.secret_key)
    )


@pytest.fixture(autouse=True)
def cancel_awaiting_payments(yookassa_client: httpx.Client):
    response = yookassa_client.get(
        url='v3/payments',
        params={'status': 'waiting_for_capture'}
    )
    assert response.status_code == 200, response.text

    for payment in response.json()['items']:
        response = yookassa_client.post(
            url=f'v3/payments/{payment['id']}/cancel',
            headers={'Idempotence-Key': str(uuid4())},
            timeout=10.0
        )
        assert response.status_code == 200, response.text