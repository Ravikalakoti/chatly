import hashlib
import hmac
import json
import shutil
import tempfile
from datetime import date
from io import BytesIO
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from accounts.models import User
from chat.services import connect_users

from . import limits
from .models import DailyUsage, Order, Wallet

SMALL_LIMITS = {"text": 2, "voice": 1, "image": 1}


def make_user(name, email):
    user = User(display_name=name, email=email)
    user.set_password("s3cret-pass!")
    user.save()
    return user


@override_settings(FREE_DAILY_LIMITS=SMALL_LIMITS)
class LimitRulesTests(TestCase):
    def setUp(self):
        self.user = make_user("Ravi", "ravi@example.com")

    def test_free_messages_then_blocked(self):
        self.assertTrue(limits.consume(self.user, "text"))
        self.assertTrue(limits.consume(self.user, "text"))
        self.assertFalse(limits.consume(self.user, "text"))
        # other kinds have their own counters
        self.assertTrue(limits.consume(self.user, "voice"))
        self.assertFalse(limits.consume(self.user, "voice"))
        status = limits.get_status(self.user)
        self.assertEqual(status["text"], {"limit": 2, "used": 2, "free_left": 0, "credits": 0, "remaining": 0})

    def test_bought_messages_are_used_after_the_free_ones(self):
        limits.add_credits(self.user, text=2)
        self.assertTrue(limits.consume(self.user, "text"))
        self.assertTrue(limits.consume(self.user, "text"))
        self.assertEqual(Wallet.objects.get(user=self.user).text_credits, 2)  # still untouched
        self.assertTrue(limits.consume(self.user, "text"))
        self.assertTrue(limits.consume(self.user, "text"))
        self.assertFalse(limits.consume(self.user, "text"))
        self.assertEqual(Wallet.objects.get(user=self.user).text_credits, 0)

    def test_free_counters_reset_on_a_new_day(self):
        with mock.patch("billing.limits.today", return_value=date(2026, 1, 1)):
            limits.consume(self.user, "image")
            self.assertFalse(limits.consume(self.user, "image"))
        with mock.patch("billing.limits.today", return_value=date(2026, 1, 2)):
            self.assertTrue(limits.consume(self.user, "image"))
        self.assertEqual(DailyUsage.objects.filter(user=self.user).count(), 2)

    def test_limits_come_from_settings(self):
        with override_settings(FREE_DAILY_LIMITS={"text": 1, "voice": 0, "image": 0}):
            self.assertTrue(limits.consume(self.user, "text"))
            self.assertFalse(limits.consume(self.user, "text"))
            self.assertFalse(limits.consume(self.user, "voice"))  # limit 0 -> nothing free


@override_settings(FREE_DAILY_LIMITS=SMALL_LIMITS)
class UploadLimitTests(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        self.a = make_user("Ravi", "ravi@example.com")
        self.b = make_user("Asha", "asha@example.com")
        self.conv, _ = connect_users(self.a, self.b)
        self.client.force_login(self.a)

    def photo(self):
        buffer = BytesIO()
        Image.new("RGB", (8, 8), "pink").save(buffer, "PNG")
        return SimpleUploadedFile("p.png", buffer.getvalue(), content_type="image/png")

    def send_photo(self):
        return self.client.post(
            reverse("attach_api", args=[self.conv.pk]), {"kind": "image", "file": self.photo()}
        )

    def test_photo_limit_returns_402_and_nothing_is_stored(self):
        with override_settings(MEDIA_ROOT=self.media):
            first = self.send_photo()
            self.assertEqual(first.status_code, 200)
            self.assertEqual(first.json()["quota"]["image"]["remaining"], 0)
            second = self.send_photo()
        self.assertEqual(second.status_code, 402)
        self.assertTrue(second.json()["limit"])
        self.assertEqual(self.conv.messages.count(), 1)

    def test_bought_photo_credit_allows_one_more(self):
        limits.add_credits(self.a, image=1)
        with override_settings(MEDIA_ROOT=self.media):
            self.assertEqual(self.send_photo().status_code, 200)
            self.assertEqual(self.send_photo().status_code, 200)
            self.assertEqual(self.send_photo().status_code, 402)


@override_settings(DEBUG=True, RAZORPAY_KEY_ID="", RAZORPAY_KEY_SECRET="")
class DemoCheckoutTests(TestCase):
    def setUp(self):
        self.user = make_user("Ravi", "ravi@example.com")
        self.client.force_login(self.user)

    def test_buy_page_needs_login_and_lists_packs(self):
        self.client.logout()
        resp = self.client.get(reverse("pricing"))
        self.assertEqual(resp.status_code, 302)
        self.client.force_login(self.user)
        resp = self.client.get(reverse("pricing"))
        self.assertContains(resp, "Starter")
        self.assertContains(resp, "Test mode")

    def test_demo_purchase_adds_the_pack_once(self):
        order = self.client.post(
            reverse("billing_order"), json.dumps({"pack": "starter"}), content_type="application/json"
        ).json()
        self.assertEqual(order["mode"], "demo")
        pay = lambda: self.client.post(  # noqa: E731
            reverse("billing_demo"), json.dumps({"order_id": order["order_id"]}), content_type="application/json"
        )
        self.assertEqual(pay().status_code, 200)
        self.assertEqual(pay().status_code, 200)  # a repeat must not add credits again
        wallet = Wallet.objects.get(user=self.user)
        self.assertEqual((wallet.text_credits, wallet.voice_credits, wallet.image_credits), (200, 20, 20))
        self.assertEqual(Order.objects.get().status, Order.PAID)

    def test_unknown_pack_is_rejected(self):
        resp = self.client.post(reverse("billing_order"), json.dumps({"pack": "nope"}), content_type="application/json")
        self.assertEqual(resp.status_code, 400)

    @override_settings(DEBUG=False)
    def test_demo_payment_is_disabled_outside_debug(self):
        resp = self.client.post(reverse("billing_demo"), json.dumps({"order_id": "demo_x"}), content_type="application/json")
        self.assertEqual(resp.status_code, 404)
        resp = self.client.post(reverse("billing_order"), json.dumps({"pack": "starter"}), content_type="application/json")
        self.assertEqual(resp.status_code, 503)


@override_settings(RAZORPAY_KEY_ID="rzp_test_x", RAZORPAY_KEY_SECRET="topsecret", RAZORPAY_WEBHOOK_SECRET="hooksecret")
class RazorpayVerificationTests(TestCase):
    def setUp(self):
        self.user = make_user("Ravi", "ravi@example.com")
        self.other = make_user("Asha", "asha@example.com")
        self.order = Order.objects.create(
            user=self.user, pack_id="plus", amount_minor=9900, currency="INR",
            text_credits=500, voice_credits=50, image_credits=50, provider_order_id="order_ABC",
        )

    def sign(self, order_id="order_ABC", payment_id="pay_1", secret="topsecret"):
        return hmac.new(secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()

    def verify(self, signature, user=None):
        self.client.force_login(user or self.user)
        body = {"razorpay_order_id": "order_ABC", "razorpay_payment_id": "pay_1", "razorpay_signature": signature}
        return self.client.post(reverse("billing_verify"), json.dumps(body), content_type="application/json")

    def test_valid_signature_adds_credits_once(self):
        self.assertEqual(self.verify(self.sign()).status_code, 200)
        self.assertEqual(self.verify(self.sign()).status_code, 200)
        self.assertEqual(Wallet.objects.get(user=self.user).text_credits, 500)

    def test_bad_signature_or_someone_elses_order_gets_nothing(self):
        self.assertEqual(self.verify("forged").status_code, 400)
        self.assertEqual(self.verify(self.sign(), user=self.other).status_code, 400)
        self.assertFalse(Wallet.objects.filter(text_credits__gt=0).exists())

    def test_webhook_needs_valid_signature_and_is_idempotent(self):
        body = json.dumps(
            {"event": "payment.captured", "payload": {"payment": {"entity": {"id": "pay_1", "order_id": "order_ABC"}}}}
        ).encode()
        good = hmac.new(b"hooksecret", body, hashlib.sha256).hexdigest()
        url = reverse("billing_webhook")

        bad = self.client.post(url, body, content_type="application/json", HTTP_X_RAZORPAY_SIGNATURE="nope")
        self.assertEqual(bad.status_code, 400)
        self.assertFalse(Wallet.objects.exists())

        for _ in range(2):
            ok = self.client.post(url, body, content_type="application/json", HTTP_X_RAZORPAY_SIGNATURE=good)
            self.assertEqual(ok.status_code, 200)
        self.assertEqual(Wallet.objects.get(user=self.user).text_credits, 500)
