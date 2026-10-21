"""
Razorpay (https://razorpay.com) integration using only the Python standard library.

Flow: the server creates an order -> the browser opens Razorpay Checkout -> Razorpay
returns a signed result -> the server checks the signature and adds the credits.
A webhook does the same check, so credits still arrive if the buyer closes the tab.
"""
import base64
import hashlib
import hmac
import json
import urllib.error
import urllib.request

from django.conf import settings

API_URL = "https://api.razorpay.com/v1/orders"


class GatewayError(Exception):
    pass


def is_configured():
    return bool(settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET)


def create_order(amount_minor, currency, receipt, notes=None):
    body = json.dumps(
        {"amount": amount_minor, "currency": currency, "receipt": receipt, "notes": notes or {}}
    ).encode()
    token = base64.b64encode(f"{settings.RAZORPAY_KEY_ID}:{settings.RAZORPAY_KEY_SECRET}".encode()).decode()
    request = urllib.request.Request(
        API_URL,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Basic {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode())
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise GatewayError(str(exc)) from exc


def _signature_ok(message, signature, secret):
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def verify_payment(order_id, payment_id, signature):
    message = f"{order_id}|{payment_id}".encode()
    return _signature_ok(message, signature, settings.RAZORPAY_KEY_SECRET)


def verify_webhook(raw_body, signature):
    return _signature_ok(raw_body, signature, settings.RAZORPAY_WEBHOOK_SECRET)
