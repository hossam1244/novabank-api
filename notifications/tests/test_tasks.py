"""Celery task behavior (eager mode)."""

import pytest
from django.core import mail

from notifications.tasks import payment_payload, send_payment_email

pytestmark = pytest.mark.django_db


class TestPaymentEmail:
    def test_email_sent_to_creator(self, org):
        payment = org.main.payments.first()
        result = send_payment_email(payment.id)
        assert result == f"emailed {org.owner.email}"
        assert len(mail.outbox) == 1
        assert payment.reference in mail.outbox[0].body or "Payment" in mail.outbox[0].subject

    def test_payment_without_creator_is_noop(self, org):
        payment = org.main.payments.first()
        payment.created_by = None
        payment.save(update_fields=["created_by"])
        assert send_payment_email(payment.id) is None
        assert len(mail.outbox) == 0


class TestPayload:
    def test_payload_shape(self, org):
        payment = org.main.payments.first()
        payload = payment_payload(payment)
        assert payload["type"] == "payment.updated"
        assert payload["payment"]["amount"] == str(payment.amount)
        assert payload["payment"]["status"] == payment.status
