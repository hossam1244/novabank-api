"""WebSocket consumer tests — auth gate and event delivery."""

import asyncio

import pytest
from channels.db import database_sync_to_async
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from rest_framework_simplejwt.tokens import AccessToken

from accounts.factories import MembershipFactory
from config.asgi import application

# transaction=True: the consumer reads the ORM from its own thread, which
# cannot see rows inside the test's outer atomic block — and shared-cache
# SQLite locks the table while that transaction is open.
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.django_db(transaction=True),
]


def ws_url(token: str | None) -> str:
    query = f"?token={token}" if token else ""
    return f"/ws/transactions/{query}"


async def connect(token=None):
    # Browsers always send an Origin header; the origin validator rejects
    # sockets without one unless ALLOWED_HOSTS is "*".
    communicator = WebsocketCommunicator(
        application,
        ws_url(token),
        headers=[(b"origin", b"http://localhost")],
    )
    accepted, _ = await communicator.connect()
    return communicator, accepted


class TestTransactionConsumer:
    async def test_anonymous_socket_closed(self):
        communicator, connected = await connect()
        assert not connected

    async def test_invalid_token_closed(self, db):
        communicator, connected = await connect("not-a-jwt")
        assert not connected

    async def test_member_receives_payment_updates(self, org):
        token = str(AccessToken.for_user(org.employee))
        communicator, connected = await connect(token)
        assert connected

        layer = get_channel_layer()
        await layer.group_send(
            f"org.{org.org.id}",
            {"type": "payment.updated", "payment": {"id": "x", "status": "settled"}},
        )
        message = await communicator.receive_json_from(timeout=5)
        assert message["type"] == "payment.updated"
        assert message["payment"]["status"] == "settled"
        await communicator.disconnect()

    async def test_member_does_not_receive_other_org_events(self, org):
        other = await database_sync_to_async(MembershipFactory)(role="owner")
        token = str(AccessToken.for_user(other.user))
        communicator, connected = await connect(token)
        assert connected

        await get_channel_layer().group_send(
            f"org.{org.org.id}",
            {"type": "payment.updated", "payment": {"id": "x"}},
        )
        # The other org's event never reaches this socket: the receive times
        # out (channels surfaces that as TimeoutError or CancelledError).
        with pytest.raises((TimeoutError, asyncio.CancelledError)):
            await communicator.receive_json_from(timeout=1)
        # After a timed-out receive, channels' disconnect() may propagate the
        # leftover CancelledError from the application task — safe to absorb.
        try:
            await communicator.disconnect()
        except asyncio.CancelledError:
            pass
