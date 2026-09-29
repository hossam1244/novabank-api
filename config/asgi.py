"""ASGI entrypoint — HTTP via Django, WebSocket via Channels routing.

`django.setup()` runs before the routing import: under standalone ASGI servers
(gunicorn + uvicorn, daphne) nothing else initializes the app registry, and
the consumer module transitively touches Django models.
"""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
django.setup()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402
from django.core.asgi import get_asgi_application  # noqa: E402

from config.routing import websocket_urlpatterns  # noqa: E402

django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AllowedHostsOriginValidator(URLRouter(websocket_urlpatterns)),
    }
)
