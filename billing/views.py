import json
import logging
import uuid

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from . import gateway
from .catalog import currency_symbol, free_limits, get_pack, packs
from .limits import add_credits, get_status, quota_rows, reset_label
from .models import Order

logger = logging.getLogger(__name__)


def _demo_allowed():
    """The fake 'test payment' only exists while developing (DEBUG on, no real gateway keys)."""
    return settings.DEBUG and not gateway.is_configured()


def _json_body(request):
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _fulfil(order):
    """
    Mark the order paid and add its credits. Safe to call many times (browser + webhook):
    the UPDATE only matches an order that is not paid yet, so credits are added exactly once.
    """
    with transaction.atomic():
        changed = Order.objects.filter(pk=order.pk).exclude(status=Order.PAID).update(
            status=Order.PAID, paid_at=timezone.now()
        )
        if changed:
            add_credits(order.user, text=order.text_credits, voice=order.voice_credits, image=order.image_credits)
    return bool(changed)


@login_required
def pricing(request):
    return render(
        request,
        "billing/buy.html",
        {
            "packs": packs(),
            "rows": quota_rows(request.user),
            "limits": free_limits(),
            "reset_label": reset_label(),
            "payments_enabled": gateway.is_configured() or _demo_allowed(),
            "demo_mode": _demo_allowed(),
            "config": {
                "orderUrl": reverse("billing_order"),
                "verifyUrl": reverse("billing_verify"),
                "demoUrl": reverse("billing_demo"),
                "chatUrl": reverse("dashboard"),
            },
        },
    )


@login_required
@require_POST
def create_order(request):
    pack = get_pack(str(_json_body(request).get("pack", "")))
    if pack is None:
        return JsonResponse({"error": "Unknown pack."}, status=400)
    if not (gateway.is_configured() or _demo_allowed()):
        return JsonResponse({"error": "Payments are not switched on yet. Please try again later."}, status=503)

    user = request.user
    order = Order.objects.create(
        user=user,
        pack_id=pack["id"],
        amount_minor=pack["amount_minor"],
        currency=settings.PAYMENT_CURRENCY,
        text_credits=pack["text"],
        voice_credits=pack["voice"],
        image_credits=pack["image"],
    )

    if gateway.is_configured():
        try:
            remote = gateway.create_order(
                order.amount_minor,
                order.currency,
                receipt=f"chatly-{order.pk}",
                notes={"user_id": str(user.pk), "pack": pack["id"]},
            )
        except gateway.GatewayError:
            logger.exception("Could not create the payment order")
            order.status = Order.FAILED
            order.save(update_fields=["status"])
            return JsonResponse({"error": "We couldn't reach the payment provider. Please try again."}, status=502)
        order.provider_order_id = remote["id"]
        order.save(update_fields=["provider_order_id"])
        return JsonResponse(
            {
                "mode": "razorpay",
                "key": settings.RAZORPAY_KEY_ID,
                "order_id": order.provider_order_id,
                "amount": order.amount_minor,
                "currency": order.currency,
                "name": "Chatly",
                "description": f"{pack['name']} pack",
                "prefill": {"name": user.name, "email": user.email or "", "contact": user.phone or ""},
            }
        )

    order.provider_order_id = f"demo_{uuid.uuid4().hex[:20]}"
    order.save(update_fields=["provider_order_id"])
    return JsonResponse(
        {
            "mode": "demo",
            "order_id": order.provider_order_id,
            "description": f"{pack['name']} pack · {pack['price_text']}",
        }
    )


@login_required
@require_POST
def verify(request):
    """Razorpay Checkout calls this (through our JS) with a signed result after the payment."""
    data = _json_body(request)
    order_id = str(data.get("razorpay_order_id", ""))
    payment_id = str(data.get("razorpay_payment_id", ""))
    signature = str(data.get("razorpay_signature", ""))
    order = Order.objects.filter(provider_order_id=order_id, user=request.user).first()
    if order is None or not gateway.verify_payment(order_id, payment_id, signature):
        return JsonResponse({"error": "We couldn't confirm that payment."}, status=400)
    if not order.provider_payment_id:
        Order.objects.filter(pk=order.pk).update(provider_payment_id=payment_id[:64])
    _fulfil(order)
    return JsonResponse({"ok": True, "quota": get_status(request.user)})


@login_required
@require_POST
def demo_pay(request):
    """Development only: pretend the payment succeeded so the whole flow can be tried without keys."""
    if not _demo_allowed():
        raise Http404()
    order_id = str(_json_body(request).get("order_id", ""))
    order = Order.objects.filter(provider_order_id=order_id, user=request.user).first()
    if order is None or not order_id.startswith("demo_"):
        return JsonResponse({"error": "Unknown order."}, status=400)
    _fulfil(order)
    return JsonResponse({"ok": True, "quota": get_status(request.user)})


@csrf_exempt
@require_POST
def webhook(request):
    """
    Razorpay -> server notification (set the URL in the Razorpay dashboard and put the
    secret in RAZORPAY_WEBHOOK_SECRET). Makes sure credits arrive even if the buyer closes the tab.
    """
    if not gateway.verify_webhook(request.body, request.headers.get("X-Razorpay-Signature", "")):
        return HttpResponse(status=400)
    event = _json_body(request)
    if event.get("event") in ("payment.captured", "order.paid"):
        payload = event.get("payload") or {}
        payment = (payload.get("payment") or {}).get("entity") or {}
        order_id = payment.get("order_id") or ((payload.get("order") or {}).get("entity") or {}).get("id")
        order = Order.objects.filter(provider_order_id=order_id).first() if order_id else None
        if order is not None:
            if payment.get("id") and not order.provider_payment_id:
                Order.objects.filter(pk=order.pk).update(provider_payment_id=str(payment["id"])[:64])
            _fulfil(order)
    return HttpResponse("ok")
