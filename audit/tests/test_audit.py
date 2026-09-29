"""Audit middleware coverage + domain events + access control."""

import pytest
from rest_framework import status

from audit.models import AuditEvent
from conftest import payment_payload

pytestmark = pytest.mark.django_db

AUDIT_URL = "/api/v1/orgs/{org}/audit/"


def audit_url(org):
    return AUDIT_URL.format(org=org.org.id)


class TestMiddleware:
    def test_mutating_api_calls_leave_trace(self, owner_api, org):
        owner_api.post(
            f"/api/v1/orgs/{org.org.id}/payments/",
            payment_payload(org.main),
            format="json",
            HTTP_IDEMPOTENCY_KEY="audit-1",
        )
        assert AuditEvent.objects.filter(action="api.request").exists()

    def test_get_requests_not_audited(self, owner_api, org):
        owner_api.get(f"/api/v1/orgs/{org.org.id}/accounts/")
        assert not AuditEvent.objects.filter(action="api.request").exists()


class TestDomainEvents:
    def test_payment_lifecycle_audited(self, employee_api, org):
        employee_api.post(
            f"/api/v1/orgs/{org.org.id}/payments/",
            payment_payload(org.main),
            format="json",
            HTTP_IDEMPOTENCY_KEY="audit-2",
        )
        actions = set(
            AuditEvent.objects.filter(organization=org.org).values_list("action", flat=True)
        )
        assert "payment.initiated" in actions
        assert "api.request" in actions

    def test_event_stores_actor_and_metadata(self, employee_api, org):
        employee_api.post(
            f"/api/v1/orgs/{org.org.id}/payments/",
            payment_payload(org.main),
            format="json",
            HTTP_IDEMPOTENCY_KEY="audit-3",
        )
        event = AuditEvent.objects.get(action="payment.initiated")
        assert event.user == org.employee
        assert event.target_type == "Payment"
        assert event.metadata["amount"] == "50.00"


class TestAuditAccess:
    def test_admin_reads_trail(self, admin_api, org):
        response = admin_api.get(audit_url(org))
        assert response.status_code == status.HTTP_200_OK

    def test_employee_blocked(self, employee_api, org):
        response = employee_api.get(audit_url(org))
        # Non-admins get an empty result, not a 403 leaking org existence.
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"] == []

    def test_outsider_blocked(self, outsider_api, org):
        response = outsider_api.get(audit_url(org))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_filter_by_action(self, admin_api, org):
        admin_api.get(f"{audit_url(org)}?action=payment.initiated")
        response = admin_api.get(f"{audit_url(org)}?action=payment.initiated")
        for row in response.json()["results"]:
            assert row["action"] == "payment.initiated"
