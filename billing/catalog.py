"""
Everything about *what is offered* lives in config/settings.py:

    FREE_DAILY_LIMITS   how many free messages each user gets per day
    CREDIT_PACKS        what people can buy when the free messages run out

This module only reads those settings, so changing a number there changes the
chat limits, the landing page, the pricing page and the checkout at once.
"""
from django.conf import settings

KINDS = ("text", "voice", "image")

# icon, short label (UI), long label (sentences)
KIND_INFO = {
    "text": {"icon": "💬", "short": "Text", "long": "text messages"},
    "voice": {"icon": "🎤", "short": "Voice", "long": "voice messages"},
    "image": {"icon": "📸", "short": "Photos", "long": "photos"},
}


def free_limits():
    return {kind: max(0, int(settings.FREE_DAILY_LIMITS.get(kind, 0))) for kind in KINDS}


def currency_symbol():
    return getattr(settings, "PAYMENT_CURRENCY_SYMBOL", "")


def _format_price(price):
    return f"{price:g}" if isinstance(price, float) else str(price)


def packs():
    """Packs ready for templates: price text, and the amount in minor units (paise/cents)."""
    result = []
    for raw in settings.CREDIT_PACKS:
        price = raw["price"]
        result.append(
            {
                "id": raw["id"],
                "name": raw["name"],
                "popular": bool(raw.get("popular")),
                "price": price,
                "price_text": f"{currency_symbol()}{_format_price(price)}",
                "amount_minor": int(round(float(price) * 100)),
                "text": int(raw.get("text", 0)),
                "voice": int(raw.get("voice", 0)),
                "image": int(raw.get("image", 0)),
            }
        )
    return result


def get_pack(pack_id):
    return next((p for p in packs() if p["id"] == pack_id), None)
