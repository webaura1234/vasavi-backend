from __future__ import annotations

from django.apps import AppConfig


class CouponsConfig(AppConfig):
    """Django application configuration for the coupons app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "coupons"
    verbose_name = "Coupons"
