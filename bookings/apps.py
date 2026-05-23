from django.apps import AppConfig


class BookingsConfig(AppConfig):
    """Configuration for the bookings application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "bookings"
    verbose_name = "Bookings"
