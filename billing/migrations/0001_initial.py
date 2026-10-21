import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DailyUsage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("day", models.DateField()),
                ("text_count", models.PositiveIntegerField(default=0)),
                ("voice_count", models.PositiveIntegerField(default=0)),
                ("image_count", models.PositiveIntegerField(default=0)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="daily_usage",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(fields=("user", "day"), name="unique_usage_per_user_day"),
                ],
            },
        ),
        migrations.CreateModel(
            name="Wallet",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("text_credits", models.PositiveIntegerField(default=0)),
                ("voice_credits", models.PositiveIntegerField(default=0)),
                ("image_credits", models.PositiveIntegerField(default=0)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="wallet",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="Order",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("pack_id", models.CharField(max_length=40)),
                (
                    "amount_minor",
                    models.PositiveIntegerField(help_text="Amount in the smallest currency unit (paise for INR)."),
                ),
                ("currency", models.CharField(default="INR", max_length=3)),
                ("text_credits", models.PositiveIntegerField(default=0)),
                ("voice_credits", models.PositiveIntegerField(default=0)),
                ("image_credits", models.PositiveIntegerField(default=0)),
                (
                    "status",
                    models.CharField(
                        choices=[("created", "Created"), ("paid", "Paid"), ("failed", "Failed")],
                        default="created",
                        max_length=10,
                    ),
                ),
                ("provider_order_id", models.CharField(blank=True, max_length=64, null=True, unique=True)),
                ("provider_payment_id", models.CharField(blank=True, default="", max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("paid_at", models.DateTimeField(blank=True, null=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="orders",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
