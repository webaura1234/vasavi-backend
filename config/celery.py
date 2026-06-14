"""
Celery application for the Vasavi backend.

Loaded from ``config/__init__.py`` so ``shared_task`` binds to this app.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

app = Celery("vasavi")

app.config_from_object("django.conf:settings", namespace="CELERY")

# Ensure Django is initialised before task modules import models.
import django

django.setup()

app.autodiscover_tasks()
