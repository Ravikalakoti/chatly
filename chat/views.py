from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_GET
import uuid
from PIL import Image, UnidentifiedImageError
from .models import Conversation, Message
from .services import broadcast_message, conversation_summaries, conversations_for

from .payloads import conversation_info, message_payload
from .services import conversation_summaries, conversations_for
from django.db import transaction
from django.views.decorators.http import require_GET, require_POST

from billing.limits import consume, get_status, limit_message

PAGE_SIZE = 40
MAX_IMAGE_MB = 8
MAX_VOICE_MB = 5
IMAGE_EXT = {"JPEG": "jpg", "PNG": "png", "GIF": "gif", "WEBP": "webp"}
VOICE_EXT = {
    "audio/webm": "webm", "video/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a",
    "audio/x-m4a": "m4a", "audio/aac": "aac", "audio/mpeg": "mp3", "audio/wav": "wav",
}



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
        "quota": get_status(request.user),
        "urls": {
            "buy": reverse("pricing"),
            "ws": "/ws/chat/",
            "conversations": reverse("conversations_api"),
            "messages": reverse("messages_api", args=[active.pk]) if active else None,
            "attach": reverse("attach_api", args=[active.pk]) if active else None,
        },
    }
    return render(
        request,
        "chat/dashboard.html",
        {"config": config, "active": active, "peer": active.other_user(request.user) if active else None},
    )


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


@login_required
@require_POST
def attach_api(request, conversation_id):
    """Send a photo or a voice message (multipart upload: file, kind, optional caption + client_id)."""
    conversation = get_object_or_404(
        conversations_for(request.user).select_related("user_a", "user_b"), pk=conversation_id
    )
    upload = request.FILES.get("file")
    kind = request.POST.get("kind")
    if upload is None or kind not in (Message.IMAGE, Message.VOICE):
        return JsonResponse({"error": "No file received."}, status=400)

    if kind == Message.IMAGE:
        if upload.size > MAX_IMAGE_MB * 1024 * 1024:
            return JsonResponse({"error": f"Photo must be under {MAX_IMAGE_MB} MB."}, status=400)
        try:
            img = Image.open(upload)
            img.verify()
            ext = IMAGE_EXT[img.format]
        except (UnidentifiedImageError, KeyError, OSError, SyntaxError):
            return JsonResponse({"error": "That file isn't a supported image (JPG, PNG, GIF, WEBP)."}, status=400)
        upload.seek(0)
    else:
        if upload.size > MAX_VOICE_MB * 1024 * 1024:
            return JsonResponse({"error": f"Voice message must be under {MAX_VOICE_MB} MB."}, status=400)
        ext = VOICE_EXT.get((upload.content_type or "").split(";")[0].strip().lower())
        if ext is None:
            return JsonResponse({"error": "Unsupported audio format."}, status=400)

    client_id = (request.POST.get("client_id") or "")[:64]
    if client_id:
        existing = Message.objects.filter(sender=request.user, client_id=client_id).first()
        if existing:
            return JsonResponse({"ok": True, "id": existing.pk})

    upload.name = f"{uuid.uuid4().hex}.{ext}"   # extension comes from our whitelist, never from the client
    # Count it against today's free limit (or a bought credit) and store it in one go.
    with transaction.atomic():
        if not consume(request.user, kind):
            return JsonResponse(
                {"error": limit_message(kind), "limit": True, "kind": kind, "quota": get_status(request.user)},
                status=402,
            )
        message = Message.objects.create(
            conversation=conversation,
            sender=request.user,
            kind=kind,
            attachment=upload,
            body=(request.POST.get("caption") or "").strip()[:500] if kind == Message.IMAGE else "",
            client_id=client_id,
        )
    Conversation.objects.filter(pk=conversation.pk).update(updated_at=message.created_at)
    quota = get_status(request.user)
    broadcast_message(conversation, message, request.user, client_id, quota=quota)
    return JsonResponse({"ok": True, "id": message.pk, "quota": quota})

