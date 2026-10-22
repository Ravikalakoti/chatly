from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ("name", "email", "phone", "date_joined", "is_staff", "email_verified", "email_verified_at")
    search_fields = ("display_name", "email", "phone", "username")
    fieldsets = UserAdmin.fieldsets + (("Chat profile", {"fields": ("display_name", "phone", "invite_code")}),)
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Chat profile", {"fields": ("display_name", "email", "phone")}),
    )
    readonly_fields = ("invite_code",)
