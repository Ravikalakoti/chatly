from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_GET

from .payloads import conversation_info, message_payload
from .services import conversation_summaries, conversations_for

PAGE_SIZE = 40


def _message_page(conversation, before=None, after=None):
    """Return (messages in ascending order, has_more_older)."""
    qs = conversation.messages.all()
    if after is not None:
        return list(qs.filter(id__gt=after).order_by("id")[:200]), False
    if before is not None:
        qs = qs.filter(id__lt=before)
    chunk = list(qs.order_by("-id")[: PAGE_SIZE + 1])
    has_more = len(chunk) > PAGE_SIZE
    return list(reversed(chunk[:PAGE_SIZE])), has_more


@login_required
def dashboard(request, conversation_id=None):
    """The WhatsApp-style screen: conversation list on the left, open chat on the right."""
    active = None
    initial_messages, has_more = [], False
    if conversation_id is not None:
        active = get_object_or_404(
            conversations_for(request.user).select_related("user_a", "user_b"), pk=conversation_id
        )
        page, has_more = _message_page(active)
        initial_messages = [message_payload(m) for m in page]

    config = {
        "me": request.user.pk,
        "active": conversation_info(active, request.user) if active else None,
        "hasMore": has_more,
        "conversations": conversation_summaries(request.user),
        "messages": initial_messages,
        "urls": {
            "ws": "/ws/chat/",
            "conversations": reverse("conversations_api"),
            "messages": reverse("messages_api", args=[active.pk]) if active else None,
        },
    }
    return render(request, "chat/dashboard.html", {"config": config, "active": active})


@login_required
@require_GET
def messages_api(request, conversation_id):
    """History (`?before=<id>`) and catch-up after a reconnect (`?after=<id>`)."""
    conversation = get_object_or_404(conversations_for(request.user), pk=conversation_id)

    def as_int(name):
        try:
            return int(request.GET[name])
        except (KeyError, ValueError):
            return None

    page, has_more = _message_page(conversation, before=as_int("before"), after=as_int("after"))
    # Include client_id on our own messages so a reconnecting tab can match them to its pending bubbles.
    payload = [
        message_payload(m, client_id=(m.client_id or None) if m.sender_id == request.user.pk else None)
        for m in page
    ]
    return JsonResponse({"messages": payload, "has_more": has_more})


@login_required
@require_GET
def conversations_api(request):
    """Used by the browser to refresh the sidebar after a dropped connection."""
    return JsonResponse({"conversations": conversation_summaries(request.user)})
