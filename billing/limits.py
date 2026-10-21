"""
Daily free limits + bought credits.

Rules
-----
* Every user gets FREE_DAILY_LIMITS[kind] free messages per day (text / voice / image).
* When the free ones for today are used up, a bought credit is spent instead.
* With no free messages and no credits left, sending is blocked.
* The free counters reset at midnight in LIMITS_TIMEZONE (default UTC).
"""
from datetime import timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.urls import reverse
from django.utils import timezone

from .catalog import KIND_INFO, KINDS, free_limits
from .models import DailyUsage, Wallet

USAGE_FIELD = {"text": "text_count", "voice": "voice_count", "image": "image_count"}
CREDIT_FIELD = {"text": "text_credits", "voice": "voice_credits", "image": "image_credits"}


def today():
    name = getattr(settings, "LIMITS_TIMEZONE", "UTC")
    tz = dt_timezone.utc if name.upper() == "UTC" else ZoneInfo(name)
    return timezone.now().astimezone(tz).date()


def reset_label():
    return f"midnight ({getattr(settings, 'LIMITS_TIMEZONE', 'UTC')})"


def get_status(user):
    """Plain dict (JSON-safe) describing what the user can still send today."""
    limits = free_limits()
    usage = DailyUsage.objects.filter(user=user, day=today()).first()
    wallet = Wallet.objects.filter(user=user).first()
    status = {}
    for kind in KINDS:
        used = getattr(usage, USAGE_FIELD[kind]) if usage else 0
        credits = getattr(wallet, CREDIT_FIELD[kind]) if wallet else 0
        free_left = max(0, limits[kind] - used)
        status[kind] = {
            "limit": limits[kind],
            "used": min(used, limits[kind]),
            "free_left": free_left,
            "credits": credits,
            "remaining": free_left + credits,
        }
    status["buy_url"] = reverse("pricing")
    return status


def quota_rows(user):
    """The same data as a list, for templates (progress bars)."""
    status = get_status(user)
    rows = []
    for kind in KINDS:
        info, data = KIND_INFO[kind], status[kind]
        percent = 100 if data["limit"] == 0 else round(100 * data["used"] / data["limit"])
        rows.append({"kind": kind, **info, **data, "percent": min(100, percent)})
    return rows


def consume(user, kind):
    """
    Spend one message of `kind`. Returns True if the user may send it (and it has been counted).
    Call this inside the same transaction that saves the message, so a failed save is rolled back.
    Both steps are single UPDATE statements, so two simultaneous sends can never overspend.
    """
    if kind not in KINDS:
        raise ValueError(f"Unknown message kind: {kind}")
    limit = free_limits()[kind]
    usage_field, credit_field = USAGE_FIELD[kind], CREDIT_FIELD[kind]
    with transaction.atomic():
        usage, _ = DailyUsage.objects.get_or_create(user=user, day=today())
        if limit > 0:
            counted = DailyUsage.objects.filter(pk=usage.pk, **{f"{usage_field}__lt": limit}).update(
                **{usage_field: F(usage_field) + 1}
            )
            if counted:
                return True
        wallet, _ = Wallet.objects.get_or_create(user=user)
        spent = Wallet.objects.filter(pk=wallet.pk, **{f"{credit_field}__gt": 0}).update(
            **{credit_field: F(credit_field) - 1}
        )
        return bool(spent)


def limit_message(kind):
    limit = free_limits()[kind]
    return (
        f"You've used all {limit} free {KIND_INFO[kind]['long']} for today. "
        f"Buy more to keep going, or come back after {reset_label()}."
    )


def add_credits(user, text=0, voice=0, image=0):
    wallet, _ = Wallet.objects.get_or_create(user=user)
    Wallet.objects.filter(pk=wallet.pk).update(
        text_credits=F("text_credits") + text,
        voice_credits=F("voice_credits") + voice,
        image_credits=F("image_credits") + image,
    )


def recommended_limit(user):
    """How many suggested profiles this user may see: `free` count, or `paid` once they have bought a pack."""
    from .models import Order

    conf = getattr(settings, "RECOMMENDED_PROFILES", {})
    free, paid = int(conf.get("free", 5)), int(conf.get("paid", 10))
    return paid if Order.objects.filter(user=user, status=Order.PAID).exists() else free
