from __future__ import annotations

from django.apps import AppConfig


class DonorsConfig(AppConfig):
    """Configuration for the donors application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "donors"
    verbose_name = "Donors"
