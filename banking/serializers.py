"""Serializers for the banking domain."""

from decimal import Decimal

from rest_framework import serializers

from banking.models import BankAccount, Card, LedgerEntry, Payment


class BankAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankAccount
        fields = (
            "id",
            "name",
            "iban",
            "currency",
            "balance",
            "is_active",
            "created_at",
        )
        read_only_fields = ("id", "iban", "balance", "created_at")


class BankAccountCreateSerializer(BankAccountSerializer):
    """Same shape as the read serializer — extra fields are read-only."""

    class Meta(BankAccountSerializer.Meta):
        pass


class PaymentSerializer(serializers.ModelSerializer):
    created_by_email = serializers.EmailField(source="created_by.email", read_only=True)

    class Meta:
        model = Payment
        fields = (
            "id",
            "kind",
            "amount",
            "currency",
            "beneficiary_name",
            "beneficiary_iban",
            "reference",
            "status",
            "failure_reason",
            "account",
            "source_account",
            "created_by_email",
            "created_at",
            "settled_at",
        )
        read_only_fields = (
            "id",
            "kind",
            "status",
            "failure_reason",
            "account",
            "source_account",
            "created_by_email",
            "created_at",
            "settled_at",
        )


class PaymentCreateSerializer(PaymentSerializer):
    """Writable view of a payment: `source_account` selects the funded account.

    Subclasses the read serializer so the 201 response (and any stored
    idempotent replay) carries the full payment representation.
    """

    source_account = serializers.UUIDField(write_only=True)
    currency = serializers.ChoiceField(choices=BankAccount.Currency.choices, required=False)

    class Meta(PaymentSerializer.Meta):
        pass


class DepositCreateSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=16, decimal_places=2, min_value=Decimal("0.01"))
    reference = serializers.CharField(max_length=140, required=False, allow_blank=True, default="")


class CardSerializer(serializers.ModelSerializer):
    account_iban = serializers.CharField(source="account.iban", read_only=True)

    class Meta:
        model = Card
        fields = (
            "id",
            "token",
            "last4",
            "expiry_month",
            "expiry_year",
            "status",
            "account",
            "account_iban",
            "created_at",
        )
        read_only_fields = fields


class CardIssueResponseSerializer(CardSerializer):
    """The full PAN appears exactly once — in the issuance response."""

    pan = serializers.CharField(read_only=True, help_text="Shown once at issuance.")

    class Meta(CardSerializer.Meta):
        fields = CardSerializer.Meta.fields + ("pan",)
        read_only_fields = fields


class LedgerEntrySerializer(serializers.ModelSerializer):
    counterparty = serializers.SerializerMethodField()

    class Meta:
        model = LedgerEntry
        fields = ("id", "amount", "created_at", "payment", "counterparty")
        read_only_fields = fields

    def get_counterparty(self, obj):
        other = (
            obj.payment.entries.exclude(account_id=obj.account_id).select_related("account").first()
        )
        return other.account.name if other else None
