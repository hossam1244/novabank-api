import pytest
from django.db import IntegrityError

from accounts.factories import MembershipFactory, OrganizationFactory, UserFactory
from accounts.models import Membership

pytestmark = pytest.mark.django_db


class TestUser:
    def test_email_login_and_str(self):
        user = UserFactory(email="boss@example.com")
        assert str(user) == "boss@example.com"
        assert user.USERNAME_FIELD == "email"

    def test_create_superuser(self, db):
        from accounts.models import User

        admin = User.objects.create_superuser("root@example.com", "root-pass-123")
        assert admin.is_staff and admin.is_superuser

    def test_emails_normalized(self, db):
        from accounts.models import User

        user = User.objects.create_user("MiXeD@EXAMPLE.COM", "pass-123456")
        # The manager lowercases the whole address for uniqueness.
        assert user.email == "mixed@example.com"


class TestMembership:
    def test_unique_per_organization(self):
        membership = MembershipFactory()
        with pytest.raises(IntegrityError):
            MembershipFactory(organization=membership.organization, user=membership.user)

    def test_role_hierarchy(self):
        owner = MembershipFactory(role=Membership.Role.OWNER)
        assert owner.at_least(Membership.Role.ADMIN)
        assert owner.at_least(Membership.Role.OWNER)

        admin = MembershipFactory(role=Membership.Role.ADMIN)
        assert admin.at_least(Membership.Role.EMPLOYEE)
        assert admin.at_least(Membership.Role.ADMIN)
        assert not admin.at_least(Membership.Role.OWNER)

        employee = MembershipFactory(role=Membership.Role.EMPLOYEE)
        assert not employee.at_least(Membership.Role.ADMIN)

    def test_str(self):
        membership = MembershipFactory()
        assert membership.role in str(membership)


class TestOrganization:
    def test_str(self):
        org = OrganizationFactory(name="Acme")
        assert str(org) == "Acme"
