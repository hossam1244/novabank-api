"""Realtime transaction updates over WebSocket.

Authentication: clients pass their JWT as a query parameter
(`ws://…/ws/transactions/?token=<access>`); anonymous sockets are closed.
A verified user joins the group of every organization they belong to, and
only receives events for those orgs.
"""

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken

ORG_GROUP = "org.{org_id}"


@database_sync_to_async
def _orgs_for_token(token: str) -> list[str] | None:
    """Validate the JWT and return the user's organization ids, or None."""
    from accounts.models import Membership

    try:
        access = AccessToken(token)
    except TokenError:
        return None
    memberships = Membership.objects.filter(user_id=access["user_id"]).values_list(
        "organization_id", flat=True
    )
    return [str(org_id) for org_id in memberships]


class TransactionConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        token = self.scope["query_string"].decode().removeprefix("token=")
        org_ids = await _orgs_for_token(token) if token else None
        if not org_ids:
            await self.close(code=4401)  # unauthorized
            return
        self.org_groups = [ORG_GROUP.format(org_id=org_id) for org_id in org_ids]
        await self.accept()
        for group in self.org_groups:
            await self.channel_layer.group_add(group, self.channel_name)

    async def disconnect(self, code):
        for group in getattr(self, "org_groups", []):
            await self.channel_layer.group_discard(group, self.channel_name)

    async def payment_updated(self, event):
        """Handler for `payment.updated` group events — forwarded as JSON."""
        await self.send_json(event)
