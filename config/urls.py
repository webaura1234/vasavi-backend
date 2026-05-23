"""Root URL configuration."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

admin_path = settings.ADMIN_URL.lstrip("/")
if not admin_path.endswith("/"):
    admin_path = f"{admin_path}/"

urlpatterns = [
    path(admin_path, admin.site.urls),
    path("api/v1/", include("config.api_urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
