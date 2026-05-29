"""Versioned API URL routing."""

from django.urls import include, path

urlpatterns = [
    path("staff/", include("accounts.staff_urls")),
    path("accounts/", include("accounts.urls")),
    path("branches/", include("branches.urls")),
    path("properties/", include("properties.urls")),
    path("donors/", include("donors.urls")),
    path("coupons/", include("coupons.urls")),
    path("bookings/", include("bookings.urls")),
    path("support/", include("support.urls")),
]
