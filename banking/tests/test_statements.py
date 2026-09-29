"""Customer-scoped PDF statements and the paginated ledger view."""

import pytest
from rest_framework import status

pytestmark = pytest.mark.django_db


def statement_url(org, account):
    return f"/api/v1/orgs/{org.org.id}/accounts/{account.id}/statement.pdf"


def transactions_url(org, account):
    return f"/api/v1/orgs/{org.org.id}/accounts/{account.id}/transactions/"


class TestStatement:
    def test_returns_pdf_with_disposition(self, employee_api, org):
        response = employee_api.get(statement_url(org, org.main))
        assert response.status_code == status.HTTP_200_OK
        assert response["Content-Type"] == "application/pdf"
        assert response.content[:5] == b"%PDF-"
        assert 'filename="statement-' in response["Content-Disposition"]

    def test_outsider_cannot_download(self, outsider_api, org):
        assert (
            outsider_api.get(statement_url(org, org.main)).status_code == status.HTTP_404_NOT_FOUND
        )

    def test_download_is_audited(self, employee_api, org):
        from audit.models import AuditEvent

        employee_api.get(statement_url(org, org.main))
        assert AuditEvent.objects.filter(action="statement.downloaded").exists()


class TestTransactions:
    def test_lists_entries_with_counterparty(self, employee_api, org):
        response = employee_api.get(transactions_url(org, org.main))
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["results"]  # seeded funding deposit present
        first = body["results"][0]
        assert "counterparty" in first
        assert "amount" in first

    def test_cursor_pagination_provided(self, employee_api, org):
        body = employee_api.get(transactions_url(org, org.main)).json()
        assert "next" in body and "previous" in body  # cursor style, not page numbers
        assert "page" not in body

    def test_outsider_sees_nothing(self, outsider_api, org):
        assert (
            outsider_api.get(transactions_url(org, org.main)).status_code
            == status.HTTP_404_NOT_FOUND
        )
