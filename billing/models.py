from django.conf import settings
from django.db import models


class DailyUsage(models.Model):
    """How many *free* messages a user has used on a given day (one row per user per day)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="daily_usage")
    day = models.DateField()
    text_count = models.PositiveIntegerField(default=0)
    voice_count = models.PositiveIntegerField(default=0)
    image_count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "day"], name="unique_usage_per_user_day")]

    def __str__(self):
        return f"{self.user} {self.day}: {self.text_count}/{self.voice_count}/{self.image_count}"


class Wallet(models.Model):
    """Messages the user bought. They are only used after the free daily messages run out and never expire."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wallet")
    text_credits = models.PositiveIntegerField(default=0)
    voice_credits = models.PositiveIntegerField(default=0)
    image_credits = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.user} wallet"


class Order(models.Model):
    CREATED, PAID, FAILED = "created", "paid", "failed"
    STATUSES = [(CREATED, "Created"), (PAID, "Paid"), (FAILED, "Failed")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="orders")
    pack_id = models.CharField(max_length=40)
    amount_minor = models.PositiveIntegerField(help_text="Amount in the smallest currency unit (paise for INR).")
    currency = models.CharField(max_length=3, default="INR")
    # What the pack contained when it was bought (so later price/pack edits never change old orders).
    text_credits = models.PositiveIntegerField(default=0)
    voice_credits = models.PositiveIntegerField(default=0)
    image_credits = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=10, choices=STATUSES, default=CREATED)
    provider_order_id = models.CharField(max_length=64, unique=True, null=True, blank=True)
    provider_payment_id = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} · {self.pack_id} · {self.status}"
