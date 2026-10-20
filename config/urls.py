from django.contrib import admin
from django.http import HttpResponse
from django.conf import settings
from django.urls import include, path, re_path
from django.views.static import serve


def healthz(request):
    """Used by Render's health check."""
    return HttpResponse("ok", content_type="text/plain")


urlpatterns = [
    path("healthz/", healthz),
    path("admin/", admin.site.urls),
    path("", include("accounts.urls")),
    path("", include("chat.urls")),
    # Serves uploaded profile photos (fine for a small app; use S3/Cloudinary when you grow).
    re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
]
