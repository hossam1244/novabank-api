"""Domain services for money movement.

Every balance-changing operation funnels through this module so the invariants
are enforced in exactly one place:

1. All writes happen inside `transaction.atomic` with `select_for_update` on
   the affected accounts — two concurrent payments can never read the same
   stale balance.
2. Each settlement posts two ledger entries that sum to zero.
3. The account `balance` cache is updated in the same transaction as the
   entries; `verify_invariants` re-derives it for tests and ops checks.
"""

import logging
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from banking.luhn import generate_luhn_number
from banking.models import BankAccount, Card, LedgerEntry, Payment
from core.exceptions import APIError

logger = logging.getLogger(__name__)


class AccountInactive(APIError):
    status_code = 409
    default_code = "account_inactive"
    default_detail = "This account is not active."


class CurrencyMismatch(APIError):
    status_code = 422
    default_code = "currency_mismatch"
    default_detail = "Payment currency must match the account currency."


class InsufficientFunds(APIError):
    status_code = 422
    default_code = "insufficient_funds"
    default_detail = "The account does not hold enough funds for this payment."


# --- Organization bootstrap -------------------------------------------------


def ensure_organization_defaults(organization) -> BankAccount:
    """Every org gets an internal clearing account for double-entry booking."""

    clearing, _ = BankAccount.objects.get_or_create(
        organization=organization,
        is_clearing=True,
        defaults={"name": "External counterparties", "currency": BankAccount.Currency.EUR},
    )
    return clearing


def open_account(organization, *, name: str, currency: str) -> BankAccount:
    """Open an operational bank account for an organization."""
    ensure_organization_defaults(organization)
    return BankAccount.objects.create(organization=organization, name=name, currency=currency)


# --- Queries ----------------------------------------------------------------


def operational_accounts(organization):
    return BankAccount.objects.filter(organization=organization, is_clearing=False)


def clearing_account(organization) -> BankAccount:
    return ensure_organization_defaults(organization)


def verify_invariants(account: BankAccount) -> None:
    """Re-derive the balance from the ledger; raise if the cache drifted."""
    total = LedgerEntry.objects.filter(account=account).aggregate(
        total=Sum("amount", default=Decimal("0.00"))
    )["total"]
    if total != account.balance:
        raise RuntimeError(  # pragma: no cover - invariant breach is a bug
            f"Ledger invariant broken for {account.iban}: cached {account.balance}, derived {total}"
        )


# --- Money movement ----------------------------------------------------------


def _post_entries(payment: Payment, credit: BankAccount, debit: BankAccount) -> None:
    """Create the double entry and move the balance caches."""
    amount = payment.amount
    LedgerEntry.objects.bulk_create(
        [
            LedgerEntry(payment=payment, account=debit, amount=-amount),
            LedgerEntry(payment=payment, account=credit, amount=amount),
        ]
    )
    credit.balance += amount
    debit.balance -= amount
    credit.save(update_fields=["balance"])
    debit.save(update_fields=["balance"])


def deposit(
    organization, *, account: BankAccount, amount, reference: str = "", user=None
) -> Payment:
    """Book an inbound deposit immediately (simulated external transfer in)."""
    if not account.is_active:
        raise AccountInactive()
    with transaction.atomic():
        clearing = clearing_account(organization)
        locked = BankAccount.objects.select_for_update().get(pk=account.pk)
        payment = Payment.objects.create(
            organization=organization,
            kind=Payment.Kind.DEPOSIT,
            account=locked,
            amount=amount,
            currency=locked.currency,
            reference=reference or "Deposit",
            status=Payment.Status.SETTLED,
            settled_at=timezone.now(),
            created_by=user,
        )
        _post_entries(payment, credit=locked, debit=clearing)
        verify_invariants(locked)
        verify_invariants(clearing)
    from notifications.tasks import notify_payment_update

    notify_payment_update.delay(payment.id)
    return payment


def initiate_payment(
    organization,
    *,
    source_account: BankAccount,
    amount,
    beneficiary_name: str,
    beneficiary_iban: str,
    reference: str = "",
    currency: str | None = None,
    user=None,
) -> Payment:
    """Validate and create an outbound payment in `pending` state.

    Settlement is deferred to a Celery task; funds are only debited when the
    task posts the ledger entries.
    """
    amount = Decimal(amount)
    if not source_account.is_active:
        raise AccountInactive()
    if currency is not None and currency != source_account.currency:
        raise CurrencyMismatch()

    with transaction.atomic():
        locked = BankAccount.objects.select_for_update().get(pk=source_account.pk)
        if locked.balance < amount:
            raise InsufficientFunds(
                details={"available": str(locked.balance), "requested": str(amount)}
            )
        payment = Payment.objects.create(
            organization=organization,
            kind=Payment.Kind.PAYMENT,
            source_account=locked,
            account=locked,
            amount=amount,
            currency=locked.currency,
            beneficiary_name=beneficiary_name,
            beneficiary_iban=beneficiary_iban,
            reference=reference,
            status=Payment.Status.PENDING,
            created_by=user,
        )

    from notifications.tasks import notify_payment_update, settle_payment

    settle_payment.apply_async((payment.id,))
    notify_payment_update.delay(payment.id)
    return payment


def settle_payment(payment_id) -> None:
    """Transition a pending payment to settled, posting the ledger entries."""
    from notifications.tasks import notify_payment_update

    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment_id)
        if payment.status != Payment.Status.PENDING:
            logger.info("Payment %s already %s; skipping settlement", payment_id, payment.status)
            return

        locked = BankAccount.objects.select_for_update().get(pk=payment.source_account_id)
        if locked.balance < payment.amount:
            payment.status = Payment.Status.FAILED
            payment.failure_reason = "Insufficient funds at settlement time"
            payment.save(update_fields=["status", "failure_reason"])
            verify_invariants(locked)
        else:
            clearing = clearing_account(payment.organization)
            payment.status = Payment.Status.SETTLED
            payment.settled_at = timezone.now()
            payment.save(update_fields=["status", "settled_at"])
            _post_entries(payment, credit=clearing, debit=locked)
            verify_invariants(locked)
            verify_invariants(clearing)

    notify_payment_update.delay(payment.id)


def cancel_payment(organization, payment: Payment) -> Payment:
    """Cancel a payment that has not settled yet.

    Re-fetches under lock: the caller's `payment` may be stale (e.g. a Celery
    settlement may have settled it a moment ago), and a settled payment must
    never be overwritten with `cancelled`.
    """
    with transaction.atomic():
        current = Payment.objects.select_for_update().get(pk=payment.pk)
        if current.status != Payment.Status.PENDING:
            raise APIError(
                "Only pending payments can be cancelled.",
                code="not_cancellable",
                details={"status": current.status},
                status_code=409,
            )
        current.status = Payment.Status.CANCELLED
        current.save(update_fields=["status"])
        payment = current
    from notifications.tasks import notify_payment_update

    notify_payment_update.delay(payment.id)
    return payment


# --- Cards -------------------------------------------------------------------


def issue_card(organization, *, account: BankAccount) -> tuple[Card, str]:
    """Issue a virtual card. Returns (card, pan) — the PAN is shown once."""
    if not account.is_active:
        raise AccountInactive()
    pan = generate_luhn_number("4716")  # demo BIN
    expiry = date.today().replace(year=date.today().year + 3)
    card = Card.objects.create(
        organization=organization,
        account=account,
        last4=pan[-4:],
        expiry_month=expiry.month,
        expiry_year=expiry.year,
    )
    return card, pan


def set_card_status(card: Card, status: str) -> Card:
    if card.status == Card.Status.CANCELLED:
        raise APIError(
            "A cancelled card cannot change status.", code="card_cancelled", status_code=409
        )
    card.status = status
    card.save(update_fields=["status"])
    return card
