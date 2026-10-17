import secrets
import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models

from .utils import normalize_phone

AVATAR_COLORS = 8


def generate_invite_code():
    return secrets.token_urlsafe(7)  # ~10 URL-safe characters


class User(AbstractUser):
    """
    A user signs up with an email OR a phone number (or both, via the admin).
    `username` is kept only because Django's admin expects it; it is generated
    automatically and users never see it.
    """

    email = models.EmailField("email address", unique=True, null=True, blank=True)
    phone = models.CharField(max_length=20, unique=True, null=True, blank=True)
    display_name = models.CharField(max_length=60, blank=True)
    invite_code = models.CharField(max_length=16, unique=True, default=generate_invite_code, editable=False)

    REQUIRED_FIELDS = ["email", "display_name"]

    def save(self, *args, **kwargs):
        self.email = (self.email or "").strip().lower() or None
        self.phone = normalize_phone(self.phone) if self.phone else None
        if not self.username:
            self.username = uuid.uuid4().hex[:20]
        super().save(*args, **kwargs)

    # --- display helpers used by the chat UI -------------------------------
    @property
    def name(self):
        return self.display_name or self.email or self.phone or self.username

    @property
    def initial(self):
        return (self.name[:1] or "?").upper()

    @property
    def avatar_index(self):
        return (self.pk or 0) % AVATAR_COLORS

    def __str__(self):
        return self.name
