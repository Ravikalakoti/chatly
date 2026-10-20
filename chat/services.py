import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db.models import Count, OuterRef, Q, Subquery

from .models import Conversation, Message
from .payloads import conversation_info, message_payload, preview_text

logger = logging.getLogger(__name__)


def user_group(user_id):
    """Every connected browser tab of a user joins this channel-layer group."""
    return f"user_{user_id}"


def get_or_create_conversation(user1, user2):
    first, second = sorted((user1, user2), key=lambda u: u.pk)
    return Conversation.objects.get_or_create(user_a=first, user_b=second)


def connect_users(user1, user2):
    """
    Make sure the two users have a conversation (used by invite links).
    If it's new, any open browser tab of either user learns about it instantly.
    """
    conversation, created = get_or_create_conversation(user1, user2)
    if created:
        layer = get_channel_layer()
        for viewer in (user1, user2):
            try:
                async_to_sync(layer.group_send)(
                    user_group(viewer.pk),
                    {
                        "type": "chat.event",
                        "payload": {"type": "conversation", "conversation": conversation_info(conversation, viewer)},
                    },
                )
            except Exception:  # never let a realtime hiccup break signup/login
                logger.exception("Could not push new-conversation event")
    return conversation, created


def broadcast_message(conversation, message, sender, client_id="", quota=None):
    """Push a stored message to every open tab of both participants (used by photo / voice upload)."""
    layer = get_channel_layer()
    for viewer in (conversation.user_a, conversation.user_b):
        payload = {
            "type": "message",
            "conversation": conversation_info(conversation, viewer),
            "message": message_payload(message, client_id if viewer.pk == sender.pk else None),
        }
        if quota is not None and viewer.pk == sender.pk:
            payload["quota"] = quota  # lets the sender's tabs update their "messages left" counters
        try:
            async_to_sync(layer.group_send)(
                user_group(viewer.pk),
                {"type": "chat.event", "payload": payload},
            )
        except Exception:
            logger.exception("Could not push message event")


def conversations_for(user):
    return Conversation.objects.filter(Q(user_a=user) | Q(user_b=user))


def conversation_summaries(user):
    """Sidebar data: one dict per conversation with last message and unread count."""
    last = Message.objects.filter(conversation=OuterRef("pk")).order_by("-id")
    qs = (
        conversations_for(user)
        .select_related("user_a", "user_b")
        .annotate(
            last_body=Subquery(last.values("body")[:1]),
            last_kind=Subquery(last.values("kind")[:1]),
            last_at=Subquery(last.values("created_at")[:1]),
            last_sender=Subquery(last.values("sender_id")[:1]),
            unread=Count("messages", filter=Q(messages__read_at__isnull=True) & ~Q(messages__sender=user)),
        )
    )
    items = []
    for conv in qs:
        info = conversation_info(conv, user)
        info.update(
            preview=preview_text(conv.last_body, conv.last_kind) if conv.last_kind else "",
            last_mine=conv.last_sender == user.pk,
            last_at=(conv.last_at or conv.created_at).isoformat(),
            has_messages=conv.last_kind is not None,
            unread=conv.unread,
        )
        items.append(info)
    items.sort(key=lambda i: i["last_at"], reverse=True)
    return items
