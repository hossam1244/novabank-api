"""Consistent error envelopes for every failure mode of the API.

Clients get the same shape everywhere::

    {"error": {"code": "insufficient_funds", "message": "...", "details": {...}}}
"""

import logging

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import exceptions as drf_exceptions
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)


class APIError(drf_exceptions.APIException):
    """Base class for domain errors raised by services."""

    status_code = 400
    default_code = "error"
    default_detail = "Something went wrong."

    def __init__(self, detail=None, *, code=None, details=None, status_code=None):
        if detail is None:
            detail = self.default_detail
        super().__init__(detail=detail, code=code or self.default_code)
        self.details = details
        if status_code is not None:
            self.status_code = status_code


def api_exception_handler(exc, context):
    """Wrap DRF/Django exceptions in the uniform error envelope."""

    if isinstance(exc, DjangoValidationError):
        exc = drf_exceptions.ValidationError(detail=exc.message_dict)

    response = drf_exception_handler(exc, context)

    if response is None:
        logger.exception("Unhandled API exception", exc_info=exc)
        return Response(
            {
                "error": {
                    "code": "internal_error",
                    "message": "An unexpected error occurred.",
                    "details": {},
                }
            },
            status=500,
        )

    if isinstance(response.data, dict) and "error" in response.data:
        # Already shaped by a domain error.
        return response

    code = "error"
    if isinstance(exc, (drf_exceptions.APIException, DjangoPermissionDenied, Http404)):
        codes = exc.get_codes() if isinstance(exc, drf_exceptions.APIException) else None
        # Field-level validation errors yield a dict of codes — fall back to
        # the exception's default code and keep the dict under `details`.
        code = codes if isinstance(codes, str) else exc.default_code
    if code == "invalid":
        code = "validation_failed"
    if code == "no_active_account":  # simplejwt's failed-login code
        code = "authentication_failed"
    if code == "throttled":
        code = "rate_limited"

    message = response.data.get("detail") if isinstance(response.data, dict) else None
    details = {}
    if message is None and isinstance(response.data, dict):
        details = response.data  # field-level validation errors
        message = "Request failed validation."

    # Domain errors may carry structured details (e.g. available funds).
    domain_details = getattr(exc, "details", None)
    if domain_details:
        details = domain_details

    response.data = {
        "error": {
            "code": code,
            "message": str(message),
            "details": details,
        }
    }
    return response
