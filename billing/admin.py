from django.contrib import admin

from .models import DailyUsage, Order, Wallet


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    """Edit the credits here to give someone free messages (e.g. a gift or a refund)."""

    list_display = ("user", "text_credits", "voice_credits", "image_credits")
    raw_id_fields = ("user",)
    search_fields = ("user__display_name", "user__email", "user__phone")


@admin.register(DailyUsage)
class DailyUsageAdmin(admin.ModelAdmin):
    list_display = ("user", "day", "text_count", "voice_count", "image_count")
    list_filter = ("day",)
    raw_id_fields = ("user",)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "pack_id", "amount_minor", "currency", "status", "created_at", "paid_at")
    list_filter = ("status", "pack_id")
    raw_id_fields = ("user",)
    readonly_fields = ("provider_order_id", "provider_payment_id", "created_at", "paid_at")
