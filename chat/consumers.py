"""
One websocket per browser tab. Instead of a channel-layer group per conversation,
every tab joins a group for its *user* (`user_<id>`). Sending a message just
publishes to both participants' groups, which keeps the sidebar, unread badges
and open chat window in sync with a single connection.

Client -> server messages (JSON):
    {"type": "message", "conversation": 1, "body": "hi", "client_id": "abc"}
    {"type": "typing",  "conversation": 1}
    {"type": "read",    "conversation": 1}
    {"type": "ping"}

Server -> client events:
    {"type": "message", "conversation": {...info}, "message": {...}}
    {"type": "typing",  "conversation": 1}
    {"type": "read",    "conversation": 1, "up_to": 42}     # the other person read your messages
    {"type": "read_self", "conversation": 1}                # you read them in another tab
    {"type": "conversation", "conversation": {...info}}     # a new contact appeared
    {"type": "pong"} / {"type": "error", "detail": "..."}
    {"type": "limit", "kind": "text", "client_id": "abc", "detail": "...", "quota": {...}}
                                                           # daily free limit used up, nothing was sent
(The "message" event also carries "quota" for the sender: how many messages they have left.)
"""
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.db import transaction
from django.utils import timezone

from billing.limits import consume, get_status, limit_message

from .models import Conversation, Message
from .payloads import conversation_info, message_payload
from .services import conversations_for, user_group

MAX_BODY_LENGTH = 4000
LIMIT_REACHED = "limit"


class ChatConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.user = self.scope["user"]
        if not self.user.is_authenticated:
            await self.close(code=4401)
            return
        self.group = user_group(self.user.pk)
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        if getattr(self, "group", None):
            await self.channel_layer.group_discard(self.group, self.channel_name)

    # ------------------------------------------------------------------ incoming
    async def receive_json(self, content, **kwargs):
        if not isinstance(content, dict):
            return
        kind = content.get("type")
        if kind == "ping":
            await self.send_json({"type": "pong"})
            return
        try:
            conversation_id = int(content.get("conversation"))
        except (TypeError, ValueError):
            return

        if kind == "message":
            await self.handle_message(conversation_id, content)
        elif kind == "typing":
            await self.handle_typing(conversation_id)
        elif kind == "read":
            await self.handle_read(conversation_id)

    async def handle_message(self, conversation_id, content):
        body = str(content.get("body") or "").strip()
        if not body:
            return
        if len(body) > MAX_BODY_LENGTH:
            await self.send_json({"type": "error", "detail": "Message is too long."})
            return
        client_id = str(content.get("client_id") or "")[:64]
        saved = await self.save_message(conversation_id, body, client_id)
        if saved is None:
            await self.send_json({"type": "error", "detail": "Conversation not found."})
            return
        if saved == LIMIT_REACHED:
            await self.send_json(
                {
                    "type": "limit",
                    "kind": "text",
                    "client_id": client_id,
                    "detail": limit_message("text"),
                    "quota": await self.quota(),
                }
            )
            return
        conversation, message = saved
        quota = await self.quota()
        for viewer in (conversation.user_a, conversation.user_b):
            payload = {
                "type": "message",
                "conversation": conversation_info(conversation, viewer),
                # client_id lets the sender's tab match this event to its pending bubble
                "message": message_payload(message, client_id if viewer.pk == self.user.pk else None),
            }
            if viewer.pk == self.user.pk:
                payload["quota"] = quota  # keeps the sender's "messages left" counters current
            await self.channel_layer.group_send(user_group(viewer.pk), {"type": "chat.event", "payload": payload})

    async def handle_typing(self, conversation_id):
        conversation = await self.get_conversation(conversation_id)
        if conversation is None:
            return
        other = conversation.other_user(self.user)
        await self.channel_layer.group_send(
            user_group(other.pk),
            {"type": "chat.event", "payload": {"type": "typing", "conversation": conversation_id}},
        )

    async def handle_read(self, conversation_id):
        result = await self.mark_read(conversation_id)
        if result is None:
            return
        conversation, newest_id = result
        if newest_id is None:
            return
        other = conversation.other_user(self.user)
        await self.channel_layer.group_send(
            user_group(other.pk),
            {
                "type": "chat.event",
                "payload": {"type": "read", "conversation": conversation_id, "up_to": newest_id},
            },
        )
        await self.channel_layer.group_send(
            self.group,
            {"type": "chat.event", "payload": {"type": "read_self", "conversation": conversation_id}},
        )

    # -------------------------------------------------------------- group events
    async def chat_event(self, event):
        await self.send_json(event["payload"])

    # ------------------------------------------------------------------ database
    @database_sync_to_async
    def get_conversation(self, conversation_id):
        return (
            conversations_for(self.user)
            .select_related("user_a", "user_b")
            .filter(pk=conversation_id)
            .first()
        )

    @database_sync_to_async
    def save_message(self, conversation_id, body, client_id):
        conversation = (
            conversations_for(self.user)
            .select_related("user_a", "user_b")
            .filter(pk=conversation_id)
            .first()
        )
        if conversation is None:
            return None
        if client_id:
            # A resend after a dropped connection: return the message we already stored.
            existing = Message.objects.filter(sender=self.user, client_id=client_id).first()
            if existing is not None:
                return conversation, existing
        # Count the message against today's free limit (or a bought credit) and store it together:
        # if saving fails, the count is rolled back too.
        with transaction.atomic():
            if not consume(self.user, Message.TEXT):
                return LIMIT_REACHED
            message = Message.objects.create(
                conversation=conversation, sender=self.user, body=body, client_id=client_id
            )
        Conversation.objects.filter(pk=conversation.pk).update(updated_at=message.created_at)
        return conversation, message

    @database_sync_to_async
    def quota(self):
        return get_status(self.user)

    @database_sync_to_async
    def mark_read(self, conversation_id):
        conversation = (
            conversations_for(self.user)
            .select_related("user_a", "user_b")
            .filter(pk=conversation_id)
            .first()
        )
        if conversation is None:
            return None
        unread = Message.objects.filter(conversation=conversation, read_at__isnull=True).exclude(sender=self.user)
        newest = unread.order_by("-id").values_list("id", flat=True).first()
        if newest is not None:
            unread.update(read_at=timezone.now())
        return conversation, newest
