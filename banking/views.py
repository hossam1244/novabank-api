"""Banking API views — all org-scoped via the URL prefix."""

from django.http import HttpResponse
from rest_framework import exceptions, generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Membership
from audit.services import record_audit
from banking import services
from banking.idempotency import IdempotencyMixin
from banking.models import BankAccount, Card, LedgerEntry, Payment
from banking.pdf import build_account_statement
from banking.serializers import (
    BankAccountCreateSerializer,
    BankAccountSerializer,
    CardIssueResponseSerializer,
    CardSerializer,
    DepositCreateSerializer,
    LedgerEntrySerializer,
    PaymentCreateSerializer,
    PaymentSerializer,
)
from banking.throttling import PaymentCreateThrottle
from core.pagination import CursorTransactionPagination, StandardPagination


class OrgApiMixin:
    """Resolve the org from the URL and 404 for non-members.

    Queryset scoping is the primary isolation control: every list/get below
    filters by `self.organization`, so a valid token from another org yields
    no data rather than a leak.
    """

    def initial(self, request, *args, **kwargs):
        membership = (
            request.user.memberships.filter(organization_id=kwargs.get("org_id"))
            .select_related("organization")
            .first()
        )
        if membership is None:
            raise exceptions.NotFound("Organization not found.")
        self.organization = membership.organization
        self.membership = membership
        super().initial(request, *args, **kwargs)

    def require_role(self, role):
        if not self.membership.at_least(role):
            raise exceptions.PermissionDenied(
                detail=f"Your role does not allow this action (needs {role})."
            )


# --- Accounts ----------------------------------------------------------------


class BankAccountListCreateView(OrgApiMixin, generics.ListCreateAPIView):
    """GET/POST /api/v1/orgs/{org_id}/accounts — list or open accounts."""

    pagination_class = StandardPagination

    def get_serializer_class(self):
        return (
            BankAccountCreateSerializer if self.request.method == "POST" else BankAccountSerializer
        )

    def get_queryset(self):
        return (
            services.operational_accounts(self.organization)
            .select_related("organization")
            .order_by("-created_at")
        )

    def perform_create(self, serializer):
        self.require_role(Membership.Role.ADMIN)
        account = serializer.save(organization=self.organization)
        record_audit(
            self.request,
            organization=self.organization,
            action="account.opened",
            target=account,
            metadata={"iban": account.iban, "currency": account.currency},
        )


class BankAccountDetailView(OrgApiMixin, generics.RetrieveAPIView):
    serializer_class = BankAccountSerializer

    def get_queryset(self):
        return services.operational_accounts(self.organization).select_related("organization")


# --- Payments ----------------------------------------------------------------


class PaymentListCreateView(OrgApiMixin, IdempotencyMixin, generics.ListCreateAPIView):
    """GET/POST /api/v1/orgs/{org_id}/payments — history and new payments.

    POST requires an `Idempotency-Key` header; retries with the same key and
    body never double-debit.
    """

    pagination_class = StandardPagination
    idempotency_required = True
    throttle_classes = [PaymentCreateThrottle]
    throttle_scope = "payments"

    def get_serializer_class(self):
        return PaymentCreateSerializer if self.request.method == "POST" else PaymentSerializer

    def get_queryset(self):
        return (
            Payment.objects.filter(organization=self.organization)
            .select_related("account", "created_by")
            .order_by("-created_at")
        )

    def perform_create(self, serializer):
        source = BankAccount.objects.filter(
            organization=self.organization,
            pk=serializer.validated_data["source_account"],
            is_clearing=False,
        ).first()
        if source is None:
            raise exceptions.ValidationError(
                {"source_account": "Unknown account in this organization."}
            )

        payment = services.initiate_payment(
            self.organization,
            source_account=source,
            amount=serializer.validated_data["amount"],
            beneficiary_name=serializer.validated_data["beneficiary_name"],
            beneficiary_iban=serializer.validated_data["beneficiary_iban"],
            reference=serializer.validated_data.get("reference", ""),
            currency=serializer.validated_data.get("currency"),
            user=self.request.user,
        )
        record_audit(
            self.request,
            organization=self.organization,
            action="payment.initiated",
            target=payment,
            metadata={"amount": str(payment.amount), "beneficiary": payment.beneficiary_name},
        )
        # Eager settlement (tests/dev) may have advanced the status after the
        # service call — always serialize the database truth.
        payment.refresh_from_db()
        serializer.instance = payment


class PaymentDetailView(OrgApiMixin, generics.RetrieveAPIView):
    serializer_class = PaymentSerializer

    def get_queryset(self):
        return Payment.objects.filter(organization=self.organization).select_related(
            "account", "created_by"
        )


class PaymentCancelView(OrgApiMixin, APIView):
    """POST /api/v1/orgs/{org_id}/payments/{id}/cancel — stop a pending payment."""

    def post(self, request, *args, **kwargs):
        payment = Payment.objects.filter(organization=self.organization, pk=kwargs["pk"]).first()
        if payment is None:
            return Response(
                {"error": {"code": "not_found", "message": "Payment not found.", "details": {}}},
                status=status.HTTP_404_NOT_FOUND,
            )
        self.require_role(Membership.Role.ADMIN)
        services.cancel_payment(self.organization, payment)
        record_audit(
            request, organization=self.organization, action="payment.cancelled", target=payment
        )
        return Response(PaymentSerializer(payment).data)


# --- Deposits (demo funding path) ---------------------------------------------


class DepositView(OrgApiMixin, generics.CreateAPIView):
    """POST /api/v1/orgs/{org_id}/accounts/{account_id}/deposits — simulate inbound funds."""

    serializer_class = DepositCreateSerializer

    def perform_create(self, serializer):
        account = BankAccount.objects.filter(
            organization=self.organization, pk=self.kwargs["account_id"], is_clearing=False
        ).first()
        if account is None:
            raise exceptions.NotFound("Account not found.")
        payment = services.deposit(
            self.organization,
            account=account,
            amount=serializer.validated_data["amount"],
            reference=serializer.validated_data["reference"] or "Deposit",
            user=self.request.user,
        )
        serializer.instance = payment
        self.created_object = payment

    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)
        if response.status_code == status.HTTP_201_CREATED and hasattr(self, "created_object"):
            response.data = PaymentSerializer(self.created_object).data
        return response


# --- Ledger ------------------------------------------------------------------


class TransactionListView(OrgApiMixin, generics.ListAPIView):
    """GET /api/v1/orgs/{org_id}/accounts/{account_id}/transactions — the ledger."""

    serializer_class = LedgerEntrySerializer
    pagination_class = CursorTransactionPagination

    def get_queryset(self):
        account = BankAccount.objects.filter(
            organization=self.organization, pk=self.kwargs["account_id"], is_clearing=False
        ).first()
        if account is None:
            return LedgerEntry.objects.none()
        return (
            LedgerEntry.objects.filter(account=account)
            .select_related("payment", "payment__account", "account")
            .prefetch_related("payment__entries__account")
            .order_by("-created_at")
        )


# --- Statements ---------------------------------------------------------------


class StatementView(OrgApiMixin, APIView):
    """GET /api/v1/orgs/{org_id}/accounts/{account_id}/statement.pdf?from&to

    Returns a PDF statement scoped to the requesting organization — the
    document stream is never reachable without a membership check.
    """

    def get(self, request, *args, **kwargs):
        account = BankAccount.objects.filter(
            organization=self.organization, pk=kwargs["account_id"], is_clearing=False
        ).first()
        if account is None:
            return Response(
                {"error": {"code": "not_found", "message": "Account not found.", "details": {}}},
                status=status.HTTP_404_NOT_FOUND,
            )
        pdf_bytes = build_account_statement(account, request.GET.get("from"), request.GET.get("to"))
        record_audit(
            request,
            organization=self.organization,
            action="statement.downloaded",
            target=account,
            metadata={"from": request.GET.get("from"), "to": request.GET.get("to")},
        )
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="statement-{account.iban}.pdf"'
        return response


# --- Cards --------------------------------------------------------------------


class CardListCreateView(OrgApiMixin, generics.ListCreateAPIView):
    """GET/POST /api/v1/orgs/{org_id}/cards — list or issue virtual cards."""

    pagination_class = StandardPagination

    def get_serializer_class(self):
        return CardSerializer  # POST response built in create()

    def get_queryset(self):
        return (
            Card.objects.filter(organization=self.organization)
            .select_related("account")
            .order_by("-created_at")
        )

    def create(self, request, *args, **kwargs):
        self.require_role(Membership.Role.ADMIN)
        account = BankAccount.objects.filter(
            organization=self.organization,
            pk=request.data.get("account"),
            is_clearing=False,
        ).first()
        if account is None:
            raise exceptions.ValidationError({"account": "Unknown account in this organization."})
        card, pan = services.issue_card(self.organization, account=account)
        record_audit(
            request,
            organization=self.organization,
            action="card.issued",
            target=card,
            metadata={"last4": card.last4},
        )
        data = CardIssueResponseSerializer(card).data
        data["pan"] = pan
        return Response(data, status=status.HTTP_201_CREATED)


class CardStatusView(OrgApiMixin, APIView):
    """POST /api/v1/orgs/{org_id}/cards/{id}/freeze | /unfreeze | /cancel"""

    allowed = {
        "freeze": Card.Status.FROZEN,
        "unfreeze": Card.Status.ACTIVE,
        "cancel": Card.Status.CANCELLED,
    }

    def post(self, request, *args, **kwargs):
        action = kwargs["action"]
        if action not in self.allowed:
            return Response(
                {"error": {"code": "not_found", "message": "Unknown action.", "details": {}}},
                status=status.HTTP_404_NOT_FOUND,
            )
        self.require_role(Membership.Role.ADMIN)
        card = Card.objects.filter(organization=self.organization, pk=kwargs["pk"]).first()
        if card is None:
            return Response(
                {"error": {"code": "not_found", "message": "Card not found.", "details": {}}},
                status=status.HTTP_404_NOT_FOUND,
            )
        services.set_card_status(card, self.allowed[action])
        record_audit(request, organization=self.organization, action=f"card.{action}", target=card)
        return Response(CardSerializer(card).data)
