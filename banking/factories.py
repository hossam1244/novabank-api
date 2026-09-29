from decimal import Decimal

import factory

from accounts.factories import OrganizationFactory
from banking.models import BankAccount, Card


class BankAccountFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = BankAccount

    organization = factory.SubFactory(OrganizationFactory)
    name = factory.Sequence(lambda n: f"Account {n}")
    currency = BankAccount.Currency.EUR
    balance = Decimal("1000.00")


class CardFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Card

    organization = factory.SubFactory(OrganizationFactory)
    account = factory.SubFactory(BankAccountFactory)
    last4 = factory.Sequence(lambda n: f"{1000 + n}"[-4:])
    expiry_month = 12
    expiry_year = 2030
