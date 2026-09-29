"""Scoped throttling — payments get their own budget."""

import pytest
from django.conf import settings
from rest_framework import status
from rest_framework.test import override_settings

from conftest import payment_payload

pytestmark = pytest.mark.django_db

PAYMENTS_URL = "/api/v1/orgs/{org}/payments/"


def payments_url(org):
    return PAYMENTS_URL.format(org=org.org.id)


def tight_throttles():
    """Keep every other REST_FRAMEWORK default (error envelope included)."""
    return {
        **settings.REST_FRAMEWORK,
        "DEFAULT_THROTTLE_CLASSES": ("rest_framework.throttling.ScopedRateThrottle",),
        "DEFAULT_THROTTLE_RATES": {
            "payments": "3/min",
            "anon": "30/min",
            "user": "120/min",
        },
    }


class TestPaymentThrottling:
    def test_payments_rate_limited_after_budget(self, employee_api, org):
        with override_settings(REST_FRAMEWORK=tight_throttles()):
            responses = [
                employee_api.post(
                    payments_url(org),
                    payment_payload(org.main, "1.00", reference=f"t{i}"),
                    format="json",
                    HTTP_IDEMPOTENCY_KEY=f"throttle-{i}",
                )
                for i in range(5)
            ]
        statuses = [r.status_code for r in responses]
        # First three pass the scoped budget; the rest are throttled.
        assert statuses[:3] == [status.HTTP_201_CREATED] * 3
        assert statuses[3] == status.HTTP_429_TOO_MANY_REQUESTS

        body = responses[3].json()
        assert body["error"]["code"] == "rate_limited"
