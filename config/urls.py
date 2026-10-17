from django.contrib import admin
from django.http import HttpResponse
from django.urls import include, path


def healthz(request):
    """Used by Render's health check."""
    return HttpResponse("ok", content_type="text/plain")


urlpatterns = [
    path("healthz/", healthz),
    path("admin/", admin.site.urls),
    path("", include("accounts.urls")),
    path("", include("chat.urls")),
]
