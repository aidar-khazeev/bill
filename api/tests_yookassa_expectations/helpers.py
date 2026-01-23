from uuid import uuid4
import httpx


# Не фикстуры, так как не хочется разбираться с typing'ом

def create_payment(
    yookassa_client: httpx.Client,
    roubles: float | str,
    auto_capture: bool = True
):
    # https://yookassa.ru/developers/api#create_payment
    return yookassa_client.post(
        url='/v3/payments',
        headers={'Idempotence-Key': str(uuid4())},
        json={
            'amount': {
                'value': str(roubles),
                'currency': 'RUB'
            },
            'confirmation': {
                'type': 'redirect',
                'enforce': False,
                'return_url': 'https://example.com'
            },
            'payment_method_data': {
                'type': 'bank_card',
                'card': {
                    'number': '5555555555554444',
                    'expiry_year': '2030',
                    'expiry_month': '12',
                    'cardholder': 'XXX',
                    'csc': '543'
                }
            },
            'capture': auto_capture
        },
        timeout=30.0
    )


def get_payment(
    yookassa_client: httpx.Client,
    id: str
):
    # https://yookassa.ru/developers/api#get_payment
    return yookassa_client.get(
        url=f'/v3/payments/{id}',
        headers={'Idempotence-Key': str(uuid4())}
    )


def capture_payment(
    yookassa_client: httpx.Client,
    id: str,
    roubles: float | str,
    idempotence_key: str | None = None
):
    # https://yookassa.ru/developers/api#capture_payment
    return yookassa_client.post(
        url=f'/v3/payments/{id}/capture',
        headers={'Idempotence-Key': idempotence_key or str(uuid4())},
        json={'amount': {'value': str(roubles), 'currency': 'RUB'}}
    )


def create_refund(
    yookassa_client: httpx.Client,
    id: str,
    roubles: float | str,
    idempotence_key: str | None = None
):
    # https://yookassa.ru/developers/api#create_refund
    return yookassa_client.post(
        url='/v3/refunds',
        headers={'Idempotence-Key': idempotence_key or str(uuid4())},
        json={
            'payment_id': id,
            'amount': {'value': str(roubles), 'currency': 'RUB'}
        }
    )
