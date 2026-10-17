from django.contrib import admin

from .models import Conversation, Message


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "user_a", "user_b", "created_at", "updated_at")
    raw_id_fields = ("user_a", "user_b")


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "sender", "short_body", "created_at", "read_at")
    raw_id_fields = ("conversation", "sender")

    @admin.display(description="Message")
    def short_body(self, obj):
        return obj.body[:60]
