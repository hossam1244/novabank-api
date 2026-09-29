"""Payment lifecycle over the API + the ledger invariants behind it."""

from decimal import Decimal

import pytest
from rest_framework import status

from banking import services
from banking.models import LedgerEntry, Payment
from conftest import payment_payload

pytestmark = pytest.mark.django_db

PAYMENTS_URL = "/api/v1/orgs/{org}/payments/"


def payments_url(org):
    return PAYMENTS_URL.format(org=org.org.id)


def make_payment(client, org, amount="50.00", key="test-key-1", **extra):
    return client.post(
        payments_url(org),
        payment_payload(org.main, amount, **extra),
        format="json",
        HTTP_IDEMPOTENCY_KEY=key,
    )


class TestPaymentCreate:
    def test_payment_settles_and_debits_balance(self, employee_api, org):
        response = make_payment(employee_api, org)
        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["status"] == "settled"  # eager Celery settles inline in tests
        org.main.refresh_from_db()
        assert str(org.main.balance) == "4950.00"
        assert LedgerEntry.objects.filter(payment_id=body["id"]).count() == 2

    def test_payment_requires_idempotency_key(self, employee_api, org):
        response = employee_api.post(payments_url(org), payment_payload(org.main), format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error"]["code"] == "idempotency_key_required"

    def test_insufficient_funds_rejected(self, employee_api, org):
        response = make_payment(employee_api, org, amount="99999.00", key="too-much")
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert response.json()["error"]["code"] == "insufficient_funds"
        details = response.json()["error"]["details"]
        assert details["available"] == "5000.00"

    def test_unknown_source_account_rejected(self, employee_api, org):
        payload = payment_payload(org.main)
        payload["source_account"] = "00000000-0000-0000-0000-000000000000"
        response = employee_api.post(
            payments_url(org), payload, format="json", HTTP_IDEMPOTENCY_KEY="nope"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_currency_mismatch_rejected(self, employee_api, org):
        response = make_payment(employee_api, org, key="curr", currency="USD")
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert response.json()["error"]["code"] == "currency_mismatch"

    def test_negative_amount_rejected(self, employee_api, org):
        response = make_payment(employee_api, org, amount="-10.00", key="neg")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_optional_fields_omitted(self, employee_api, org):
        payload = {
            "source_account": str(org.main.id),
            "amount": "5.00",
            "beneficiary_name": "ACME Supplier Ltd",
            "beneficiary_iban": "CY17002001280000001200527600",
        }
        response = employee_api.post(
            payments_url(org), payload, format="json", HTTP_IDEMPOTENCY_KEY="no-extras"
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["reference"] == ""

    def test_outsider_cannot_pay(self, outsider_api, org):
        response = make_payment(outsider_api, org, key="outsider")
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestPaymentListAndDetail:
    def test_history_lists_org_payments(self, employee_api, org):
        make_payment(employee_api, org, key="one")
        make_payment(employee_api, org, amount="10.00", key="two")
        response = employee_api.get(payments_url(org))
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] >= 2


class TestPaymentCancel:
    def test_admin_cancels_pending_payment(self, admin_api, org):
        # Defer settlement (eager Celery would settle it instantly in tests).
        from unittest.mock import patch

        with patch("notifications.tasks.settle_payment.apply_async"):
            payment = services.initiate_payment(
                org.org,
                source_account=org.main,
                amount=Decimal("100.00"),
                beneficiary_name="X",
                beneficiary_iban="CY17X",
                reference="cancel-me",
            )
        response = admin_api.post(f"{payments_url(org)}{payment.id}/cancel/")
        assert response.status_code == status.HTTP_200_OK
        payment.refresh_from_db()
        assert payment.status == Payment.Status.CANCELLED
        # Cancelled payments never touch the ledger.
        assert not LedgerEntry.objects.filter(payment=payment).exists()

    def test_cannot_cancel_settled_payment(self, admin_api, org):
        payment = Payment.objects.filter(
            organization=org.org, status=Payment.Status.SETTLED
        ).first()
        response = admin_api.post(f"{payments_url(org)}{payment.id}/cancel/")
        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.json()["error"]["code"] == "not_cancellable"

    def test_employee_cannot_cancel(self, employee_api, org):
        payment = Payment.objects.filter(organization=org.org).first()
        response = employee_api.post(f"{payments_url(org)}{payment.id}/cancel/")
        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestLedgerInvariants:
    def test_every_settled_payment_sums_to_zero(self, employee_api, org):
        make_payment(employee_api, org, key="invariant")
        for payment in Payment.objects.filter(status=Payment.Status.SETTLED):
            total = sum(e.amount for e in payment.entries.all())
            assert total == Decimal("0.00")

    def test_balances_always_match_ledger(self, employee_api, org):
        make_payment(employee_api, org, key="invariant")
        make_payment(employee_api, org, amount="7.50", key="invariant2")
        for account in org.org.bank_accounts.all():
            services.verify_invariants(account)  # raises on drift

    def test_deposit_and_payment_balance_the_clearing_account(self, employee_api, org):
        before = services.clearing_account(org.org).balance
        make_payment(employee_api, org, amount="80.00", key="clear")
        clearing = services.clearing_account(org.org)
        clearing.refresh_from_db()
        assert clearing.balance - before == Decimal("80.00")  # money left the org
