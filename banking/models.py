"""The banking domain: accounts, payments, the ledger, cards, idempotency.

Design notes
------------
* Balances are *derived* from `LedgerEntry` rows; `BankAccount.balance` is a
  cache updated inside the same database transaction as the entries. Tests
  assert the invariant `balance == sum(entries.amount)` after every movement.
* Every payment posts exactly two entries that sum to zero (double entry):
  the counterparty side books against the organization's clearing account.
* Full card numbers are never persisted — only `last4` (see services.issue_card).
"""

import secrets
import uuid
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


def generate_iban() -> str:
    """Pseudo-IBAN for the demo (NV + check digits + bank code + random)."""
    return f"NV{secrets.randbelow(90) + 10}NVBK{secrets.token_hex(5).upper()}"


class BankAccount(models.Model):
    """A business account owned by an organization."""

    class Currency(models.TextChoices):
        EUR = "EUR", "Euro"
        USD = "USD", "US Dollar"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "accounts.Organization", on_delete=models.CASCADE, related_name="bank_accounts"
    )
    name = models.CharField(max_length=200)
    iban = models.CharField(max_length=34, unique=True, default=generate_iban)
    currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.EUR)
    balance = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0.00"))
    is_clearing = models.BooleanField(
        default=False,
        help_text="Internal counterpart account used to balance double entries.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [models.Index(fields=["organization", "-created_at"])]
        constraints = [
            # Operational accounts can never go negative; the internal
            # clearing account may (it balances external counterparties).
            models.CheckConstraint(
                condition=models.Q(is_clearing=True) | models.Q(balance__gte=0),
                name="operational_balance_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} · {self.iban}"


class Payment(models.Model):
    """A money movement request — outbound payment or inbound deposit."""

    class Kind(models.TextChoices):
        PAYMENT = "payment", "Outbound payment"
        DEPOSIT = "deposit", "Inbound deposit"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SETTLED = "settled", "Settled"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "accounts.Organization", on_delete=models.CASCADE, related_name="payments"
    )
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.PAYMENT)
    source_account = models.ForeignKey(
        BankAccount,
        on_delete=models.PROTECT,
        related_name="outgoing_payments",
        null=True,
        blank=True,
    )
    account = models.ForeignKey(
        BankAccount,
        on_delete=models.PROTECT,
        related_name="payments",
        help_text="The organizational account this movement belongs to.",
    )
    amount = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    currency = models.CharField(max_length=3, choices=BankAccount.Currency.choices)
    beneficiary_name = models.CharField(max_length=200, blank=True)
    beneficiary_iban = models.CharField(max_length=34, blank=True)
    reference = models.CharField(max_length=140, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    failure_reason = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, related_name="payments"
    )
    created_at = models.DateTimeField(default=timezone.now)
    settled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["organization", "-created_at"]),
            models.Index(fields=["status"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="payment_amount_positive"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.kind} {self.amount} {self.currency} ({self.status})"


class LedgerEntry(models.Model):
    """An immutable, signed posting. Negative = debit, positive = credit.

    The pair of entries for a payment always sums to exactly zero, and an
    account's balance cache always equals the sum of its entries.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="entries")
    account = models.ForeignKey(BankAccount, on_delete=models.PROTECT, related_name="entries")
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [
            models.Index(fields=["account", "-created_at"]),
            models.Index(fields=["payment"]),
        ]

    def __str__(self) -> str:
        sign = "+" if self.amount >= 0 else "-"
        return f"{self.account.name}{sign}{abs(self.amount)}"


class Card(models.Model):
    """A virtual card against a bank account. PAN shown once at issuance."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        FROZEN = "frozen", "Frozen"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "accounts.Organization", on_delete=models.CASCADE, related_name="cards"
    )
    account = models.ForeignKey(BankAccount, on_delete=models.PROTECT, related_name="cards")
    token = models.UUIDField(default=uuid.uuid4, unique=True)
    last4 = models.CharField(max_length=4)
    expiry_month = models.PositiveSmallIntegerField()
    expiry_year = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [models.Index(fields=["organization", "-created_at"])]

    def __str__(self) -> str:
        return f"Card •••• {self.last4} ({self.status})"


class IdempotencyRecord(models.Model):
    """Stores the response of an idempotent request for replay.

    Scoped to (organization, endpoint, key): a client retrying a payment with
    the same key gets the original response instead of a second debit.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "accounts.Organization", on_delete=models.CASCADE, related_name="idempotency_records"
    )
    user = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, related_name="+"
    )
    endpoint = models.CharField(max_length=200)
    key = models.CharField(max_length=100)
    request_hash = models.CharField(max_length=64)
    response_status = models.PositiveSmallIntegerField()
    response_body = models.JSONField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "endpoint", "key"], name="unique_idempotency_key"
            )
        ]

    def __str__(self) -> str:
        return f"{self.endpoint}#{self.key}"
