"""Celery application for NovaBank — settlement and notification tasks."""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("novabank")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
