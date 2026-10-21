import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db.models import Case, Count, IntegerField, OuterRef, Q, Subquery, Value, When

from django.contrib.auth import get_user_model
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.timesince import timesince

from billing.limits import recommended_limit

from .models import ChatRequest, Conversation, Message, Notification
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


# ---------------------------------------------------------------- discover & requests
OPPOSITE_GENDER = {"male": "female", "female": "male"}


def can_request(sender, receiver):
    """Men can only request women and women only men (other / unset gender: nobody)."""
    return sender.pk != receiver.pk and OPPOSITE_GENDER.get(sender.gender) == receiver.gender


def recommended_profiles(user):
    """
    Suggested people for `user`: the opposite gender, never someone already chatting with them
    or waiting on their answer. Capped by the plan (5 free / 10 paid, see RECOMMENDED_PROFILES).
    Returns (profiles, limit). Each profile gets `.request_sent` (True if we already asked them).
    """
    limit = recommended_limit(user)
    target = OPPOSITE_GENDER.get(user.gender)
    if not target or limit <= 0:
        return [], limit

    chatting = set()
    for a, b in conversations_for(user).values_list("user_a_id", "user_b_id"):
        chatting.update((a, b))
    incoming = set(ChatRequest.objects.filter(receiver=user, status=ChatRequest.PENDING).values_list("sender_id", flat=True))
    sent = set(ChatRequest.objects.filter(sender=user, status=ChatRequest.PENDING).values_list("receiver_id", flat=True))
    declined_me = set(ChatRequest.objects.filter(sender=user, status=ChatRequest.DECLINED).values_list("receiver_id", flat=True))

    people = list(
        get_user_model()
        .objects.filter(is_active=True, gender=target)
        .exclude(pk__in=chatting | incoming | declined_me | {user.pk})
        # people with a photo first, then the most recently active; random order inside each group
        .annotate(no_photo=Case(When(avatar="", then=Value(1)), default=Value(0), output_field=IntegerField()))
        .order_by("no_photo", "-last_login", "?")[:limit]
    )
    today = timezone.localdate()
    for person in people:
        person.request_sent = person.pk in sent
        dob = person.date_of_birth
        person.is_new = (timezone.now() - person.date_joined).days < 7
        person.active_now = bool(person.last_login and (timezone.now() - person.last_login).total_seconds() < 24 * 3600)
        person.age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day)) if dob else None
    return people, limit


def incoming_requests(user):
    return ChatRequest.objects.filter(receiver=user, status=ChatRequest.PENDING).select_related("sender")


def send_chat_request(sender, receiver):
    """
    Returns (state, conversation) where state is one of:
    "sent", "already_sent", "connected" (they had already asked us -> auto-accepted),
    "exists" (already chatting), "forbidden" (wrong gender combination).
    """
    if not can_request(sender, receiver):
        return "forbidden", None
    existing = conversations_for(sender).filter(
        user_a_id__in=[sender.pk, receiver.pk], user_b_id__in=[sender.pk, receiver.pk]
    ).first()
    if existing:
        return "exists", existing
    with transaction.atomic():
        reverse_req = ChatRequest.objects.filter(sender=receiver, receiver=sender, status=ChatRequest.PENDING).first()
        if reverse_req:
            reverse_req.status = ChatRequest.ACCEPTED
            reverse_req.save(update_fields=["status"])
            conversation, _ = connect_users(sender, receiver)
            return "connected", conversation
        req, created = ChatRequest.objects.get_or_create(sender=sender, receiver=receiver)
        if not created:
            if req.status == ChatRequest.DECLINED:
                return "forbidden", None  # they said no; don't allow spamming
            return "already_sent", None
    return "sent", None


def answer_chat_request(user, request_id, accept):
    """Receiver accepts (-> conversation) or declines. Returns the conversation or None."""
    with transaction.atomic():
        req = ChatRequest.objects.select_for_update().filter(
            pk=request_id, receiver=user, status=ChatRequest.PENDING
        ).select_related("sender").first()
        if req is None:
            return None
        req.status = ChatRequest.ACCEPTED if accept else ChatRequest.DECLINED
        req.save(update_fields=["status"])
    if accept:
        return connect_users(user, req.sender)[0]
    return None


# ---------------------------------------------------------------- notifications (bell)
def unseen_count(user):
    return Notification.objects.filter(user=user, seen_at__isnull=True).count()


def mark_conversation_notifications_seen(user, conversation_id):
    """Opening / reading a chat clears its message notifications."""
    Notification.objects.filter(
        user=user, kind=Notification.MESSAGE, conversation_id=conversation_id, seen_at__isnull=True
    ).update(seen_at=timezone.now())


def notification_payload(user, limit=15):
    items = []
    for n in Notification.objects.filter(user=user).select_related("actor")[:limit]:
        who = n.actor.name
        if n.kind == Notification.REQUEST:
            text, url = f"{who} sent you a chat request 💌", reverse("home") + "#requests"
        elif n.kind == Notification.ACCEPTED:
            text = f"{who} accepted your request 💗"
            conv = conversations_for(user).filter(
                user_a_id__in=[user.pk, n.actor_id], user_b_id__in=[user.pk, n.actor_id]
            ).first()
            url = reverse("chat", args=[conv.pk]) if conv else reverse("home")
        else:
            text = f"{who} sent you {n.count} new message{'s' if n.count != 1 else ''} 💬"
            url = reverse("chat", args=[n.conversation_id]) if n.conversation_id else reverse("dashboard")
        items.append(
            {
                "id": n.pk,
                "text": text,
                "url": url,
                "seen": n.seen_at is not None,
                "ago": timesince(n.updated_at).split(",")[0] + " ago",
                "avatar": n.actor.avatar_url,
                "initial": n.actor.initial,
                "color": n.actor.avatar_index,
            }
        )
    return {"unseen": unseen_count(user), "items": items}
