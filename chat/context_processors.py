from django.db.models import Q

from .models import Message


def nav(request):
    """Unread-message count for the "Chats" badge in the top / bottom navigation."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    unread = (
        Message.objects.filter(read_at__isnull=True)
        .filter(Q(conversation__user_a=user) | Q(conversation__user_b=user))
        .exclude(sender=user)
        .count()
    )
    return {
        "nav_unread": unread,
        "needs_email_verify": bool(user.email) and not user.email_verified,
    }
