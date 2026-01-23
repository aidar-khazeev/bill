import sys
import pytest
import pathlib
import httpx

sys.path.append(str(pathlib.Path(__file__).parent.parent/'src'))
sys.path.append(str(pathlib.Path(__file__).parent))


@pytest.fixture
def yookassa_client():
    from settings import yookassa_settings
    return httpx.Client(
        base_url=yookassa_settings.base_url,
        auth=httpx.BasicAuth(yookassa_settings.shop_id, yookassa_settings.secret_key)
    )