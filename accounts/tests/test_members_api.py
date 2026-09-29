"""Member management and RBAC."""

import pytest
from rest_framework import status

from accounts.models import Membership, User

pytestmark = pytest.mark.django_db

MEMBERS_URL = "/api/v1/orgs/{org}/members/"


def members_url(org):
    return MEMBERS_URL.format(org=org.org.id)


def member_url(org, membership):
    return f"{MEMBERS_URL.format(org=org.org.id)}{membership.id}/"


class TestMemberList:
    def test_members_see_the_team(self, employee_api, org):
        response = employee_api.get(members_url(org))
        assert response.status_code == status.HTTP_200_OK
        emails = {m["user"]["email"] for m in response.json()["results"]}
        assert emails == {org.owner.email, org.admin.email, org.employee.email}

    def test_outsider_gets_404_not_a_leak(self, outsider_api, org):
        assert outsider_api.get(members_url(org)).status_code == status.HTTP_404_NOT_FOUND


class TestMemberInvite:
    def test_admin_invites_new_user_with_temp_password(self, admin_api, org):
        response = admin_api.post(
            members_url(org),
            {"email": "newbie@example.com", "role": "employee"},
        )
        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["temp_password"]
        assert User.objects.filter(email="newbie@example.com").exists()

        # The temp password actually works for login.
        login = admin_api.post(
            "/api/v1/auth/token/",
            {"email": "newbie@example.com", "password": body["temp_password"]},
        )
        assert login.status_code == status.HTTP_200_OK

    def test_admin_attaches_existing_user_without_password(self, admin_api, org):
        User.objects.create_user("already@example.com", "pass-123456")
        response = admin_api.post(
            members_url(org), {"email": "already@example.com", "role": "employee"}
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert "temp_password" not in response.json()

    def test_employee_cannot_invite(self, employee_api, org):
        response = employee_api.post(
            members_url(org), {"email": "nope@example.com", "role": "employee"}
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_admin_cannot_grant_owner_role(self, admin_api, org):
        response = admin_api.post(
            members_url(org), {"email": "newbie@example.com", "role": "owner"}
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_duplicate_member_rejected(self, admin_api, org):
        response = admin_api.post(
            members_url(org), {"email": org.employee.email, "role": "employee"}
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestMemberRoles:
    def test_owner_promotes_employee_to_admin(self, owner_api, org):
        membership = Membership.objects.get(user=org.employee, organization=org.org)
        response = owner_api.patch(member_url(org, membership), {"role": "admin"})
        assert response.status_code == status.HTTP_200_OK
        membership.refresh_from_db()
        assert membership.role == Membership.Role.ADMIN

    def test_admin_cannot_change_roles(self, admin_api, org):
        membership = Membership.objects.get(user=org.employee, organization=org.org)
        response = admin_api.patch(member_url(org, membership), {"role": "admin"})
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_last_owner_cannot_be_demoted(self, owner_api, org):
        membership = Membership.objects.get(user=org.owner, organization=org.org)
        response = owner_api.patch(member_url(org, membership), {"role": "employee"})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        membership.refresh_from_db()
        assert membership.role == Membership.Role.OWNER

    def test_second_owner_can_be_demoted(self, owner_api, org):
        Membership.objects.create(
            user=User.objects.create_user("co@example.com", "pass-123456"),
            organization=org.org,
            role=Membership.Role.OWNER,
        )
        membership = Membership.objects.get(user=org.owner, organization=org.org)
        response = owner_api.patch(member_url(org, membership), {"role": "admin"})
        assert response.status_code == status.HTTP_200_OK


class TestMemberRemoval:
    def test_admin_removes_employee(self, admin_api, org):
        membership = Membership.objects.get(user=org.employee, organization=org.org)
        response = admin_api.delete(member_url(org, membership))
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not Membership.objects.filter(pk=membership.pk).exists()

    def test_owner_cannot_be_removed(self, admin_api, org):
        membership = Membership.objects.get(user=org.owner, organization=org.org)
        response = admin_api.delete(member_url(org, membership))
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_employee_cannot_remove_anyone(self, employee_api, org):
        target = Membership.objects.get(user=org.admin, organization=org.org)
        response = employee_api.delete(member_url(org, target))
        assert response.status_code == status.HTTP_403_FORBIDDEN
