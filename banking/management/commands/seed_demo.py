"""Seed a demo organization with users, accounts, payments and cards.

Usage:  python manage.py seed_demo
"""

from decimal import Decimal

from django.core.management.base import BaseCommand

from accounts.models import Membership, Organization, User
from banking import services
from banking.models import BankAccount

DEMO_PASSWORD = "Passw0rd!demo"


class Command(BaseCommand):
    help = "Create demo data: one organization, three users, two accounts, history, cards."

    def handle(self, *args, **options):
        if User.objects.filter(email__endswith="@novabank.demo").exists():
            self.stdout.write(self.style.WARNING("Demo data already exists — skipping."))
            return

        org = Organization.objects.create(name="Acme Trading Ltd")

        owner = User.objects.create_user(
            "owner@novabank.demo", DEMO_PASSWORD, first_name="Omar", last_name="Owner"
        )
        admin = User.objects.create_user(
            "admin@novabank.demo", DEMO_PASSWORD, first_name="Amina", last_name="Admin"
        )
        employee = User.objects.create_user(
            "employee@novabank.demo", DEMO_PASSWORD, first_name="Emad", last_name="Employee"
        )
        Membership.objects.create(user=owner, organization=org, role=Membership.Role.OWNER)
        Membership.objects.create(user=admin, organization=org, role=Membership.Role.ADMIN)
        Membership.objects.create(user=employee, organization=org, role=Membership.Role.EMPLOYEE)

        main = services.open_account(org, name="Main EUR", currency=BankAccount.Currency.EUR)
        savings = services.open_account(org, name="Savings EUR", currency=BankAccount.Currency.EUR)

        services.deposit(
            org, account=main, amount=Decimal("25000.00"), reference="Opening funding", user=owner
        )
        services.deposit(
            org,
            account=savings,
            amount=Decimal("5000.00"),
            reference="Transfer to savings",
            user=owner,
        )

        services.initiate_payment(
            org,
            source_account=main,
            amount=Decimal("1200.00"),
            beneficiary_name="Cyprus Electricity Authority",
            beneficiary_iban="CY17002001280000001200527600",
            reference="January bill",
            user=employee,
        )
        # Demo-only: hold settlement so this payment can be shown cancelled —
        # with eager Celery the settlement task would otherwise run instantly.
        from unittest.mock import patch

        with patch("notifications.tasks.settle_payment.apply_async"):
            pending = services.initiate_payment(
                org,
                source_account=main,
                amount=Decimal("350.00"),
                beneficiary_name="Media House Ltd",
                beneficiary_iban="CY17002001280000001200527601",
                reference="Ad campaign",
                user=employee,
            )
        services.cancel_payment(org, pending)

        card_main, _ = services.issue_card(org, account=main)
        card_savings, _ = services.issue_card(org, account=savings)

        main.refresh_from_db()
        savings.refresh_from_db()

        self.stdout.write(self.style.SUCCESS("Demo organization seeded:\n"))
        self.stdout.write(f"  Organization: {org.name} ({org.id})\n")
        self.stdout.write(f"  Users (password for all: {DEMO_PASSWORD}):\n")
        for user, role in ((owner, "owner"), (admin, "admin"), (employee, "employee")):
            self.stdout.write(f"    {user.email:28s} role={role}")
        self.stdout.write(f"\n  Main EUR:    {main.iban}  balance {main.balance} EUR")
        self.stdout.write(f"  Savings EUR: {savings.iban}  balance {savings.balance} EUR")
        self.stdout.write(f"  Cards: •••• {card_main.last4}, •••• {card_savings.last4}")
        self.stdout.write(
            "\n  Log in: POST /api/v1/auth/token/ "
            '{"email": "owner@novabank.demo", "password": f"{DEMO_PASSWORD}"}'
        )
