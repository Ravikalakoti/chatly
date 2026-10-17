"""Small helpers that turn model objects into JSON-friendly dicts for the browser."""
from django.urls import reverse

PREVIEW_LENGTH = 60


def conversation_info(conversation, viewer):
    """Describe a conversation from the point of view of `viewer` (the other person's name, etc.)."""
    other = conversation.other_user(viewer)
    return {
        "id": conversation.pk,
        "name": other.name,
        "initial": other.initial,
        "color": other.avatar_index,
        "url": reverse("chat", args=[conversation.pk]),
    }


def message_payload(message, client_id=None):
    return {
        "id": message.pk,
        "conversation": message.conversation_id,
        "sender": message.sender_id,
        "body": message.body,
        "created_at": message.created_at.isoformat(),
        "read": message.read_at is not None,
        "client_id": client_id,
    }


def preview_text(body):
    flat = " ".join(body.split())
    return flat if len(flat) <= PREVIEW_LENGTH else flat[: PREVIEW_LENGTH - 1] + "…"
