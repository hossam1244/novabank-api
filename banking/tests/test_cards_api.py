"""Virtual card lifecycle."""

import pytest
from rest_framework import status

from banking.models import Card

pytestmark = pytest.mark.django_db

CARDS_URL = "/api/v1/orgs/{org}/cards/"


def cards_url(org):
    return CARDS_URL.format(org=org.org.id)


class TestCardIssue:
    def test_admin_issues_card_pan_shown_once(self, admin_api, org):
        response = admin_api.post(cards_url(org), {"account": str(org.main.id)})
        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["pan"].startswith("4716") and len(body["pan"]) == 16
        assert body["last4"] == body["pan"][-4:]

        # The full PAN is never stored — only last4.
        card = Card.objects.get(pk=body["id"])
        assert card.last4 == body["last4"]

        # And never appears in the list endpoint.
        listing = admin_api.get(cards_url(org)).json()["results"]
        assert all("pan" not in row for row in listing)

    def test_employee_cannot_issue_cards(self, employee_api, org):
        response = employee_api.post(cards_url(org), {"account": str(org.main.id)})
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_unknown_account_rejected(self, admin_api, org):
        response = admin_api.post(
            cards_url(org), {"account": "00000000-0000-0000-0000-000000000000"}
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_issued_pan_is_luhn_valid(self, admin_api, org):
        from banking.luhn import luhn_checksum_valid

        body = admin_api.post(cards_url(org), {"account": str(org.main.id)}).json()
        assert luhn_checksum_valid(body["pan"])


class TestCardStatus:
    def test_freeze_and_unfreeze(self, admin_api, org):
        freeze = admin_api.post(f"{cards_url(org)}{org.card.id}/freeze/")
        assert freeze.status_code == status.HTTP_200_OK
        assert freeze.json()["status"] == "frozen"

        unfreeze = admin_api.post(f"{cards_url(org)}{org.card.id}/unfreeze/")
        assert unfreeze.json()["status"] == "active"

    def test_cancelled_card_is_terminal(self, admin_api, org):
        admin_api.post(f"{cards_url(org)}{org.card.id}/cancel/")
        response = admin_api.post(f"{cards_url(org)}{org.card.id}/unfreeze/")
        assert response.status_code == status.HTTP_409_CONFLICT

    def test_employee_cannot_freeze(self, employee_api, org):
        response = employee_api.post(f"{cards_url(org)}{org.card.id}/freeze/")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_list_masks_everything(self, employee_api, org):
        response = employee_api.get(cards_url(org))
        assert response.status_code == status.HTTP_200_OK
        for row in response.json()["results"]:
            assert set(row) >= {"last4", "token", "status"}
            assert "pan" not in row
