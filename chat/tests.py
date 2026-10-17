from channels.db import database_sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.test import TestCase, TransactionTestCase
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
