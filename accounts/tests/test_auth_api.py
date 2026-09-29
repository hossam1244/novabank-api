"""Registration, login, token rotation and profile."""

import pytest
from rest_framework import status

from accounts.models import Membership, User
from conftest import PASSWORD

pytestmark = pytest.mark.django_db

REGISTER_URL = "/api/v1/auth/register/"
TOKEN_URL = "/api/v1/auth/token/"
REFRESH_URL = "/api/v1/auth/token/refresh/"
ME_URL = "/api/v1/me/"


def register_payload(email="new.owner@example.com", org_name="Fresh Ltd"):
    return {
        "email": email,
        "password": "SuperSecret123",
        "first_name": "Nadia",
        "last_name": "New",
        "organization_name": org_name,
    }


class TestRegister:
    def test_register_creates_org_owner_and_tokens(self, api):
        response = api.post(REGISTER_URL, register_payload())
        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["access"] and body["refresh"]
        assert body["organization"]["name"] == "Fresh Ltd"

        user = User.objects.get(email="new.owner@example.com")
        assert Membership.objects.filter(user=user, role=Membership.Role.OWNER).exists()
        # Registration bootstraps the org's clearing account for double entry.
        from banking.models import BankAccount

        assert BankAccount.objects.filter(
            organization=user.memberships.first().organization, is_clearing=True
        ).exists()

    def test_register_duplicate_email_rejected(self, api):
        api.post(REGISTER_URL, register_payload())
        response = api.post(REGISTER_URL, register_payload(org_name="Other"))
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error"]["code"] == "validation_failed"

    def test_register_weak_password_rejected(self, api):
        payload = register_payload()
        payload["password"] = "short"
        response = api.post(REGISTER_URL, payload)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_register_audited(self, api):
        api.post(REGISTER_URL, register_payload())
        from audit.models import AuditEvent

        assert AuditEvent.objects.filter(action="auth.registered").exists()


class TestLogin:
    def test_login_returns_tokens(self, api, org):
        response = api.post(TOKEN_URL, {"email": org.owner.email, "password": PASSWORD})
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["access"]

    def test_login_wrong_password(self, api, org):
        response = api.post(TOKEN_URL, {"email": org.owner.email, "password": "wrong"})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json()["error"]["code"] == "authentication_failed"

    def test_refresh_rotation_blacklists_old_token(self, api, org):
        tokens = api.post(TOKEN_URL, {"email": org.owner.email, "password": PASSWORD}).json()

        first_refresh = api.post(REFRESH_URL, {"refresh": tokens["refresh"]}).json()

        # Reusing the original refresh token now fails — it was blacklisted.
        replay = api.post(REFRESH_URL, {"refresh": tokens["refresh"]})
        assert replay.status_code == status.HTTP_401_UNAUTHORIZED
        assert first_refresh["access"] != tokens["access"]


class TestMe:
    def test_me_requires_auth(self, api):
        assert api.get(ME_URL).status_code == status.HTTP_401_UNAUTHORIZED

    def test_me_lists_memberships_and_roles(self, owner_api, org):
        response = owner_api.get(ME_URL)
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["user"]["email"] == org.owner.email
        roles = {m["organization"]["id"]: m["role"] for m in body["memberships"]}
        assert roles[str(org.org.id)] == "owner"


class TestErrorEnvelope:
    def test_not_authenticated_shape(self, api):
        body = api.get(ME_URL).json()
        assert set(body["error"]) == {"code", "message", "details"}
