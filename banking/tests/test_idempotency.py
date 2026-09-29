"""The idempotency contract — the piece that prevents double debits."""

import pytest
from rest_framework import status

from banking.models import IdempotencyRecord, Payment
from conftest import payment_payload

pytestmark = pytest.mark.django_db

PAYMENTS_URL = "/api/v1/orgs/{org}/payments/"


def payments_url(org):
    return PAYMENTS_URL.format(org=org.org.id)


class TestReplay:
    def test_retry_replays_response_without_second_debit(self, employee_api, org):
        payload = payment_payload(org.main, "100.00")
        first = employee_api.post(
            payments_url(org), payload, format="json", HTTP_IDEMPOTENCY_KEY="abc-123"
        )
        retry = employee_api.post(
            payments_url(org), payload, format="json", HTTP_IDEMPOTENCY_KEY="abc-123"
        )

        assert first.status_code == status.HTTP_201_CREATED
        assert retry.status_code == status.HTTP_201_CREATED
        assert retry.json()["id"] == first.json()["id"]
        assert retry.headers["Idempotency-Replayed"] == "true"

        # Exactly one payment, one debit (the fixture's deposits excluded).
        assert Payment.objects.filter(kind=Payment.Kind.PAYMENT).count() == 1
        org.main.refresh_from_db()
        assert str(org.main.balance) == "4900.00"

    def test_validation_errors_are_replayed_too(self, employee_api, org):
        payload = payment_payload(org.main, "999999.00")  # insufficient funds
        first = employee_api.post(
            payments_url(org), payload, format="json", HTTP_IDEMPOTENCY_KEY="err-key"
        )
        retry = employee_api.post(
            payments_url(org), payload, format="json", HTTP_IDEMPOTENCY_KEY="err-key"
        )
        assert first.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert retry.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert retry.headers["Idempotency-Replayed"] == "true"


class TestKeyReuse:
    def test_same_key_different_body_rejected(self, employee_api, org):
        employee_api.post(
            payments_url(org),
            payment_payload(org.main, "10.00"),
            format="json",
            HTTP_IDEMPOTENCY_KEY="conflict",
        )
        response = employee_api.post(
            payments_url(org),
            payment_payload(org.main, "20.00"),  # different amount
            format="json",
            HTTP_IDEMPOTENCY_KEY="conflict",
        )
        assert response.status_code == status.HTTP_409_CONFLICT

    def test_keys_scoped_per_organization(self, employee_api, outsider_api, outsider, org):
        """The same key in a different org is a different operation."""

        from decimal import Decimal

        from banking import services

        outsider_account = services.open_account(outsider.org, name="Outsider EUR", currency="EUR")
        services.deposit(outsider.org, account=outsider_account, amount=Decimal("500.00"))

        first = employee_api.post(
            payments_url(org),
            payment_payload(org.main, "10.00"),
            format="json",
            HTTP_IDEMPOTENCY_KEY="shared-key",
        )
        outsider_url = PAYMENTS_URL.format(org=outsider.org.id)
        second = outsider_api.post(
            outsider_url,
            payment_payload(outsider_account, "10.00"),
            format="json",
            HTTP_IDEMPOTENCY_KEY="shared-key",
        )
        assert first.status_code == status.HTTP_201_CREATED
        assert second.status_code == status.HTTP_201_CREATED
        assert second.json()["id"] != first.json()["id"]


class TestRecordStorage:
    def test_record_stored_with_rendered_response(self, employee_api, org):
        employee_api.post(
            payments_url(org),
            payment_payload(org.main, "15.00"),
            format="json",
            HTTP_IDEMPOTENCY_KEY="stored",
        )
        record = IdempotencyRecord.objects.get(key="stored")
        assert record.response_status == 201
        assert record.response_body["amount"] == "15.00"
        assert len(record.request_hash) == 64
