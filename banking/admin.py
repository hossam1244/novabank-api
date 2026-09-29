from django.contrib import admin

from banking.models import BankAccount, Card, IdempotencyRecord, LedgerEntry, Payment


@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "iban", "currency", "balance", "is_clearing")
    list_filter = ("currency", "is_clearing")
    search_fields = ("name", "iban", "organization__name")


class LedgerEntryInline(admin.TabularInline):
    model = LedgerEntry
    extra = 0
    can_delete = False


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("id", "organization", "kind", "amount", "currency", "status", "created_at")
    list_filter = ("status", "kind", "currency")
    search_fields = ("reference", "beneficiary_iban", "organization__name")
    inlines = (LedgerEntryInline,)


@admin.register(Card)
class CardAdmin(admin.ModelAdmin):
    list_display = ("last4", "organization", "account", "status", "created_at")
    list_filter = ("status",)


@admin.register(IdempotencyRecord)
class IdempotencyRecordAdmin(admin.ModelAdmin):
    list_display = ("endpoint", "key", "organization", "response_status", "created_at")
    search_fields = ("key", "organization__name")
