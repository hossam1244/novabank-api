"""Bank account endpoints and org isolation."""

import pytest
from rest_framework import status

from banking.models import BankAccount

pytestmark = pytest.mark.django_db

ACCOUNTS_URL = "/api/v1/orgs/{org}/accounts/"


def accounts_url(org):
    return ACCOUNTS_URL.format(org=org.org.id)


class TestAccountList:
    def test_lists_only_operational_accounts(self, employee_api, org):
        response = employee_api.get(accounts_url(org))
        assert response.status_code == status.HTTP_200_OK
        ibans = {row["iban"] for row in response.json()["results"]}
        expected = {org.main.iban, org.savings.iban}
        assert ibans == expected  # clearing account is never exposed

    def test_outsider_gets_404(self, outsider_api, org):
        assert outsider_api.get(accounts_url(org)).status_code == status.HTTP_404_NOT_FOUND


class TestAccountCreate:
    def test_admin_opens_account(self, admin_api, org):
        response = admin_api.post(accounts_url(org), {"name": "Payroll EUR", "currency": "EUR"})
        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["iban"].startswith("NV")
        assert body["balance"] == "0.00"
        assert BankAccount.objects.filter(iban=body["iban"], is_clearing=False).exists()

    def test_employee_cannot_open_account(self, employee_api, org):
        response = employee_api.post(accounts_url(org), {"name": "Sneaky EUR", "currency": "EUR"})
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_account_opening_audited(self, admin_api, org):
        from audit.models import AuditEvent

        admin_api.post(accounts_url(org), {"name": "Payroll EUR", "currency": "EUR"})
        assert AuditEvent.objects.filter(action="account.opened").exists()


class TestAccountDetail:
    def test_member_reads_balance(self, employee_api, org):
        response = employee_api.get(f"{accounts_url(org)}{org.main.id}/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["balance"] == "5000.00"

    def test_cross_org_account_invisible(self, outsider_api, org):
        assert (
            outsider_api.get(f"{accounts_url(org)}{org.main.id}/").status_code
            == status.HTTP_404_NOT_FOUND
        )


class TestDeposits:
    def test_deposit_updates_balance(self, employee_api, org):
        response = employee_api.post(
            f"{accounts_url(org)}{org.main.id}/deposits/",
            {"amount": "250.00", "reference": "Top-up"},
        )
        assert response.status_code == status.HTTP_201_CREATED
        org.main.refresh_from_db()
        assert str(org.main.balance) == "5250.00"
        assert response.json()["status"] == "settled"
