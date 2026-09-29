"""Development settings — permissive, SQLite unless DATABASE_URL is provided."""

from .base import *  # noqa: F403
from .base import env

DEBUG = True

ALLOWED_HOSTS = ["*"]

# Default to SQLite so `make dev` works with zero infrastructure; the docker
# compose stack exports DATABASE_URL and gets PostgreSQL.
DATABASES = {
    "default": env.db_url("DATABASE_URL", default="sqlite:///db.sqlite3"),
}

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Single-process dev server: keep everything in memory unless the full docker
# stack is running (it exports CHANNEL_LAYER_BACKEND=channels_redis...).
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": env("CHANNEL_LAYER_BACKEND", default="channels.layers.InMemoryChannelLayer"),
    }
}
