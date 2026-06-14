"""Root URL configuration."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.db import connection
from django.http import JsonResponse
from django.urls import include, path


def health_check(request):
    """Liveness and readiness probe for load balancers."""
    try:
        connection.ensure_connection()
        db_ok = True
    except Exception:
        db_ok = False

    status = 200 if db_ok else 503
    return JsonResponse(
        {"status": "ok" if db_ok else "degraded", "db": db_ok},
        status=status,
    )


admin_path = settings.ADMIN_URL.lstrip("/")
if not admin_path.endswith("/"):
    admin_path = f"{admin_path}/"

urlpatterns = [
    path("health/", health_check, name="health-check"),
    path(admin_path, admin.site.urls),
    path("api/v1/", include("config.api_urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
