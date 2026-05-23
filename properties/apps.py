from __future__ import annotations

from django.apps import AppConfig


class PropertiesConfig(AppConfig):
    """Configuration for the properties application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "properties"
    verbose_name = "Properties"
