"""Test settings — in-memory everything, fast and deterministic."""

import os

from .base import *  # noqa: F403
from .base import env

DEBUG = False

if "DATABASE_URL" in os.environ:
    # CI exports DATABASE_URL to run the same suite against PostgreSQL.
    DATABASES = {"default": env.db_url("DATABASE_URL")}
else:
    # Shared-cache in-memory SQLite: WebSocket consumer tests read the ORM
    # from other threads via database_sync_to_async, and a plain :memory:
    # database is private to each connection.
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": "file:memorydb_novabank?mode=memory&cache=shared",
            "TEST": {"NAME": "file:memorydb_novabank?mode=memory&cache=shared"},
        }
    }

# Settlement / notification Celery tasks run inline and raise on failure.
CELERY_TASK_ALWAYS_EAGER = True

# No broker needed in tests.
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Keep throttles out of the way; the throttling suite overrides settings itself.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_THROTTLE_CLASSES": (),
}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

USE_TZ = True
