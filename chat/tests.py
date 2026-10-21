from channels.db import database_sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from accounts.models import User

from .consumers import ChatConsumer
from .models import Message
from .routing import websocket_urlpatterns
from .services import connect_users, conversation_summaries


def make_user(name, email):
    user = User(display_name=name, email=email)
    user.set_password("s3cret-pass!")
    user.save()
    return user


class ViewTests(TestCase):
    def setUp(self):
        self.a = make_user("Ravi", "ravi@example.com")
        self.b = make_user("Asha", "asha@example.com")
        self.c = make_user("Outsider", "out@example.com")
        self.conv, _ = connect_users(self.a, self.b)
        for i in range(55):
            Message.objects.create(conversation=self.conv, sender=self.a if i % 2 else self.b, body=f"m{i}")

    def test_dashboard_and_pagination(self):
        self.client.force_login(self.a)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)
        resp = self.client.get(reverse("chat", args=[self.conv.pk]))
        self.assertEqual(resp.status_code, 200)
        config = resp.context["config"]
        self.assertEqual(len(config["messages"]), 40)
        self.assertTrue(config["hasMore"])
        oldest = config["messages"][0]["id"]
        older = self.client.get(reverse("messages_api", args=[self.conv.pk]), {"before": oldest}).json()
        self.assertEqual(len(older["messages"]), 15)
        self.assertFalse(older["has_more"])

    def test_cannot_open_someone_elses_conversation(self):
        self.client.force_login(self.c)
        self.assertEqual(self.client.get(reverse("chat", args=[self.conv.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("messages_api", args=[self.conv.pk])).status_code, 404)

    def test_sidebar_summary_unread(self):
        summary = conversation_summaries(self.a)
        self.assertEqual(len(summary), 1)
        self.assertEqual(summary[0]["name"], "Asha")
        self.assertEqual(summary[0]["unread"], sum(1 for i in range(55) if i % 2 == 0))


class ConsumerTests(TransactionTestCase):
    def setUp(self):
        self.a = make_user("Ravi", "ravi@example.com")
        self.b = make_user("Asha", "asha@example.com")
        self.c = make_user("Outsider", "out@example.com")
        self.conv, _ = connect_users(self.a, self.b)

    async def connect_as(self, user):
        communicator = WebsocketCommunicator(URLRouter(websocket_urlpatterns), "/ws/chat/")
        communicator.scope["user"] = user
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        return communicator

    async def test_message_typing_and_read_flow(self):
        ca, cb = await self.connect_as(self.a), await self.connect_as(self.b)

        await ca.send_json_to({"type": "message", "conversation": self.conv.pk, "body": " hello ", "client_id": "x1"})
        own = await ca.receive_json_from()
        got = await cb.receive_json_from()
        self.assertEqual(own["type"], "message")
        self.assertEqual(own["message"]["body"], "hello")
        self.assertEqual(own["message"]["client_id"], "x1")  # sender gets its client_id back
        self.assertEqual(own["conversation"]["name"], "Asha")
        self.assertIsNone(got["message"]["client_id"])       # recipient does not
        self.assertEqual(got["conversation"]["name"], "Ravi")

        # resending the same client_id must not create a duplicate
        await ca.send_json_to({"type": "message", "conversation": self.conv.pk, "body": "hello", "client_id": "x1"})
        await ca.receive_json_from()
        await cb.receive_json_from()
        count = await database_sync_to_async(Message.objects.count)()
        self.assertEqual(count, 1)

        await cb.send_json_to({"type": "typing", "conversation": self.conv.pk})
        self.assertEqual((await ca.receive_json_from())["type"], "typing")

        await cb.send_json_to({"type": "read", "conversation": self.conv.pk})
        receipt = await ca.receive_json_from()
        self.assertEqual(receipt["type"], "read")
        self.assertEqual(receipt["up_to"], own["message"]["id"])
        self.assertEqual((await cb.receive_json_from())["type"], "read_self")
        unread = await database_sync_to_async(Message.objects.filter(read_at__isnull=True).count)()
        self.assertEqual(unread, 0)

        await ca.disconnect()
        await cb.disconnect()

    async def test_outsider_cannot_post_or_listen(self):
        outsider = await self.connect_as(self.c)
        await outsider.send_json_to({"type": "message", "conversation": self.conv.pk, "body": "sneaky"})
        reply = await outsider.receive_json_from()
        self.assertEqual(reply["type"], "error")
        count = await database_sync_to_async(Message.objects.count)()
        self.assertEqual(count, 0)
        await outsider.disconnect()

    async def test_anonymous_is_rejected(self):
        from django.contrib.auth.models import AnonymousUser

        communicator = WebsocketCommunicator(URLRouter(websocket_urlpatterns), "/ws/chat/")
        communicator.scope["user"] = AnonymousUser()
        connected, _ = await communicator.connect()
        self.assertFalse(connected)

    async def test_invalid_payloads_are_ignored(self):
        ca = await self.connect_as(self.a)
        await ca.send_json_to({"type": "message", "conversation": "abc", "body": "x"})
        await ca.send_json_to({"type": "message", "conversation": self.conv.pk, "body": "   "})
        await ca.send_json_to({"type": "message", "conversation": self.conv.pk, "body": "y" * 4001})
        self.assertEqual((await ca.receive_json_from())["type"], "error")
        await ca.disconnect()


class LimitConsumerTests(TransactionTestCase):
    """Free daily limits over the websocket."""

    def setUp(self):
        self.a = make_user("Ravi", "ravi@example.com")
        self.b = make_user("Asha", "asha@example.com")
        self.conv, _ = connect_users(self.a, self.b)

    async def connect_as(self, user):
        communicator = WebsocketCommunicator(URLRouter(websocket_urlpatterns), "/ws/chat/")
        communicator.scope["user"] = user
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        return communicator

    async def test_text_limit_blocks_then_bought_message_unblocks(self):
        from billing.limits import add_credits

        with override_settings(FREE_DAILY_LIMITS={"text": 1, "voice": 1, "image": 1}):
            ca, cb = await self.connect_as(self.a), await self.connect_as(self.b)

            await ca.send_json_to({"type": "message", "conversation": self.conv.pk, "body": "one", "client_id": "m1"})
            first = await ca.receive_json_from()
            await cb.receive_json_from()
            self.assertEqual(first["type"], "message")
            self.assertEqual(first["quota"]["text"]["remaining"], 0)

            await ca.send_json_to({"type": "message", "conversation": self.conv.pk, "body": "two", "client_id": "m2"})
            blocked = await ca.receive_json_from()
            self.assertEqual(blocked["type"], "limit")
            self.assertEqual(blocked["kind"], "text")
            self.assertEqual(blocked["client_id"], "m2")
            self.assertEqual(await database_sync_to_async(Message.objects.count)(), 1)

            await database_sync_to_async(add_credits)(self.a, text=1)
            await ca.send_json_to({"type": "message", "conversation": self.conv.pk, "body": "three", "client_id": "m3"})
            sent = await ca.receive_json_from()
            await cb.receive_json_from()
            self.assertEqual(sent["type"], "message")
            self.assertEqual(await database_sync_to_async(Message.objects.count)(), 2)

            await ca.disconnect()
            await cb.disconnect()

    async def test_resending_the_same_message_does_not_use_another_free_message(self):
        with override_settings(FREE_DAILY_LIMITS={"text": 1, "voice": 1, "image": 1}):
            ca, cb = await self.connect_as(self.a), await self.connect_as(self.b)
            for _ in range(2):  # same client_id twice (e.g. a resend after reconnect)
                await ca.send_json_to({"type": "message", "conversation": self.conv.pk, "body": "hi", "client_id": "same"})
                self.assertEqual((await ca.receive_json_from())["type"], "message")
                await cb.receive_json_from()
            self.assertEqual(await database_sync_to_async(Message.objects.count)(), 1)
            await ca.disconnect()
            await cb.disconnect()


class DiscoverAndRequestTests(TestCase):
    def setUp(self):
        def mk(name, email, gender):
            u = make_user(name, email)
            u.gender = gender
            u.save()
            return u

        self.man = mk("Man", "m@x.com", "male")
        self.women = [mk(f"W{i}", f"w{i}@x.com", "female") for i in range(8)]
        self.men2 = mk("M2", "m2@x.com", "male")

    def test_free_user_sees_five_opposite_gender(self):
        from .services import recommended_profiles

        people, limit = recommended_profiles(self.man)
        self.assertEqual(limit, 5)
        self.assertEqual(len(people), 5)
        self.assertTrue(all(p.gender == "female" for p in people))

    @override_settings(RECOMMENDED_PROFILES={"free": 2, "paid": 10})
    def test_limit_follows_setting_and_paid_orders(self):
        from billing.models import Order
        from .services import recommended_profiles

        self.assertEqual(len(recommended_profiles(self.man)[0]), 2)
        Order.objects.create(user=self.man, pack_id="plus", amount_minor=9900, status=Order.PAID)
        self.assertEqual(len(recommended_profiles(self.man)[0]), 8)

    def test_same_gender_request_blocked(self):
        from .services import send_chat_request

        self.assertEqual(send_chat_request(self.man, self.men2)[0], "forbidden")

    def test_request_accept_creates_conversation(self):
        from .models import ChatRequest
        from .services import answer_chat_request, send_chat_request

        woman = self.women[0]
        self.assertEqual(send_chat_request(self.man, woman)[0], "sent")
        self.assertEqual(send_chat_request(self.man, woman)[0], "already_sent")
        req = ChatRequest.objects.get()
        self.assertIsNone(answer_chat_request(self.man, req.pk, True))  # only receiver can answer
        conv = answer_chat_request(woman, req.pk, True)
        self.assertTrue(conv.includes(self.man) and conv.includes(woman))

    def test_declined_cannot_resend_and_dashboard_renders(self):
        from .models import ChatRequest
        from .services import answer_chat_request, send_chat_request

        woman = self.women[0]
        send_chat_request(self.man, woman)
        answer_chat_request(woman, ChatRequest.objects.get().pk, False)
        self.assertEqual(send_chat_request(self.man, woman)[0], "forbidden")
        self.client.force_login(self.man)
        self.assertEqual(self.client.get("/chat/").status_code, 200)
        r = self.client.post(f"/chat/request/send/{self.women[1].pk}/")
        self.assertEqual(r.status_code, 302)
