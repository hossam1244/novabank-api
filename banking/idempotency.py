"""Request idempotency for unsafe POST endpoints (payments first, but reusable).

Protocol (Stripe-style):

* Client sends `Idempotency-Key: <unique-per-operation>` on POST.
* First request executes and its rendered response is stored.
* A retry with the same key and the same body replays the stored response and
  is marked with the `Idempotency-Replayed: true` header — no second debit.
* The same key with a *different* body is a client bug and rejected with 409.
* Concurrent duplicates race on the unique constraint; the loser replays the
  winner's stored response.
"""

import hashlib
import json
import logging

from django.core.serializers.json import DjangoJSONEncoder
from django.http import HttpResponse
from django.utils.crypto import constant_time_compare
from rest_framework import exceptions, status
from rest_framework.exceptions import APIException
from rest_framework.response import Response

from banking.models import IdempotencyRecord

logger = logging.getLogger(__name__)

IDEMPOTENCY_HEADER = "Idempotency-Key"
REPLAY_HEADER = "Idempotency-Replayed"


class IdempotencyKeyReused(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "This idempotency key was already used with a different request body."
    default_code = "idempotency_key_reused"


class IdempotencyMixin:
    """Add to a CreateAPIView (or any view with `.create`) to make POST idempotent."""

    idempotency_required = True
    idempotency_endpoint = None  # defaults to request path

    def create(self, request, *args, **kwargs):
        key = request.headers.get(IDEMPOTENCY_HEADER)
        if not key:
            if self.idempotency_required:
                return Response(
                    {
                        "error": {
                            "code": "idempotency_key_required",
                            "message": (
                                f"The {IDEMPOTENCY_HEADER} header is required for this endpoint."
                            ),
                            "details": {},
                        }
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            return super().create(request, *args, **kwargs)

        endpoint = self.idempotency_endpoint or request.path
        request_hash = hashlib.sha256(
            (request.body or b"") + b"|" + request.user.email.encode()
        ).hexdigest()

        existing = self._lookup(request, endpoint, key)
        if existing is not None:
            return self._replay_or_conflict(existing, request_hash)

        try:
            response = super().create(request, *args, **kwargs)
        except exceptions.APIException as exc:
            # Domain errors (e.g. insufficient funds) are definitive outcomes:
            # let DRF build the error response, then cache it for replay so a
            # client retry doesn't re-run validation or re-attempt the debit.
            response = self.handle_exception(exc)
            self._store_or_race(request, endpoint, key, request_hash, response)
            return response
        return self._store_or_race(request, endpoint, key, request_hash, response)

    # -- internals ------------------------------------------------------------

    def _lookup(self, request, endpoint, key):
        org = getattr(self, "organization", None)
        if org is None:
            return None
        return IdempotencyRecord.objects.filter(
            organization=org, endpoint=endpoint, key=key
        ).first()

    def _replay_or_conflict(self, record, request_hash):
        if not constant_time_compare(record.request_hash, request_hash):
            raise IdempotencyKeyReused()
        response = HttpResponse(
            content=json.dumps(record.response_body),
            status=record.response_status,
            headers={REPLAY_HEADER: "true", "Content-Type": "application/json"},
        )
        logger.info("Replaying idempotent response for key %s", record.key)
        return response

    def _store_or_race(self, request, endpoint, key, request_hash, response):
        # Definitive outcomes (2xx and 4xx) are cached; server errors are not
        # — the client is expected to retry them with the same key.
        if response.status_code >= 500:
            return response
        org = getattr(self, "organization", None)
        # Serialize the response *data* — the response itself is not rendered
        # yet (that happens in finalize_response, after dispatch). Round-trip
        # through DjangoJSONEncoder so UUIDs/Decimals/datetimes become plain
        # JSON types before hitting the JSONField.
        response_body = json.loads(json.dumps(response.data, cls=DjangoJSONEncoder))
        try:
            IdempotencyRecord.objects.create(
                organization=org,
                user=request.user if request.user.is_authenticated else None,
                endpoint=endpoint,
                key=key,
                request_hash=request_hash,
                response_status=response.status_code,
                response_body=response_body,
            )
        except Exception:
            # Lost the race to another worker processing the same key.
            existing = self._lookup(request, endpoint, key)
            if existing is not None:
                return self._replay_or_conflict(existing, request_hash)
            logger.exception("Could not persist idempotency record for %s", key)
            raise
        return response
