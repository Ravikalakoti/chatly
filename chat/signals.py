"""Creates bell notifications whenever a message or a chat request is saved."""
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from .models import ChatRequest, Message, Notification


@receiver(post_save, sender=Message)
def notify_new_message(sender, instance, created, **kwargs):
    if not created:
        return
    conversation = instance.conversation
    target = conversation.other_user(instance.sender)
    existing = Notification.objects.filter(
        user=target, kind=Notification.MESSAGE, conversation=conversation, seen_at__isnull=True
    ).first()
    if existing:  # "Asha sent 3 new messages" instead of 3 separate lines
        existing.count += 1
        existing.save(update_fields=["count", "updated_at"])
    else:
        Notification.objects.create(
            user=target, actor=instance.sender, kind=Notification.MESSAGE, conversation=conversation
        )


@receiver(post_save, sender=ChatRequest)
def notify_chat_request(sender, instance, created, **kwargs):
    if created and instance.status == ChatRequest.PENDING:
        Notification.objects.create(user=instance.receiver, actor=instance.sender, kind=Notification.REQUEST)
        return
    if instance.status in (ChatRequest.ACCEPTED, ChatRequest.DECLINED):
        # the receiver has dealt with it, so the "wants to chat" line is no longer news
        Notification.objects.filter(
            user=instance.receiver, actor=instance.sender, kind=Notification.REQUEST, seen_at__isnull=True
        ).update(seen_at=timezone.now())
    if instance.status == ChatRequest.ACCEPTED and not created:
        Notification.objects.create(user=instance.sender, actor=instance.receiver, kind=Notification.ACCEPTED)
