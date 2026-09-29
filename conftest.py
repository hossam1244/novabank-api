"""Shared fixtures: a fully wired demo org with funded accounts."""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from rest_framework.test import APIClient

from accounts.factories import MembershipFactory
from accounts.models import Membership
from banking import services

PASSWORD = "test-Password1"


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def org(db):
    """Organization with owner/admin/employee, two funded accounts, one card."""
    bundle = SimpleNamespace(password=PASSWORD)
    bundle.org = MembershipFactory(role=Membership.Role.OWNER).organization
    bundle.owner = bundle.org.memberships.first().user
    bundle.admin = MembershipFactory(organization=bundle.org, role=Membership.Role.ADMIN).user
    bundle.employee = MembershipFactory(organization=bundle.org, role=Membership.Role.EMPLOYEE).user
    bundle.main = services.open_account(bundle.org, name="Main EUR", currency="EUR")
    bundle.savings = services.open_account(bundle.org, name="Savings EUR", currency="EUR")
    services.deposit(
        bundle.org,
        account=bundle.main,
        amount=Decimal("5000.00"),
        reference="Funding",
        user=bundle.owner,
    )
    services.deposit(
        bundle.org,
        account=bundle.savings,
        amount=Decimal("1000.00"),
        reference="Savings",
        user=bundle.owner,
    )
    bundle.card, _ = services.issue_card(bundle.org, account=bundle.main)
    return bundle


def auth(client, user):
    client.force_authenticate(user=user)
    return client


def authenticated(user):
    """A fresh client per role — tests routinely exercise two roles at once."""
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def owner_api(org):
    return authenticated(org.owner)


@pytest.fixture
def admin_api(org):
    return authenticated(org.admin)


@pytest.fixture
def employee_api(org):
    return authenticated(org.employee)


@pytest.fixture
def outsider(api, db):
    """A user with a valid token but no membership in `org`."""
    other = MembershipFactory(role=Membership.Role.OWNER)
    return SimpleNamespace(user=other.user, org=other.organization)


@pytest.fixture
def outsider_api(outsider):
    return authenticated(outsider.user)


def payment_payload(source_account, amount="50.00", **extra):
    return {
        "source_account": str(source_account.id),
        "amount": amount,
        "beneficiary_name": "ACME Supplier Ltd",
        "beneficiary_iban": "CY17002001280000001200527600",
        "reference": "Invoice 42",
        **extra,
    }
