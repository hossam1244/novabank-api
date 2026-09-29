"""Banking routes — everything nested under the organization."""

from django.urls import path

from banking import views

urlpatterns = [
    path(
        "orgs/<uuid:org_id>/accounts/",
        views.BankAccountListCreateView.as_view(),
        name="account-list",
    ),
    path(
        "orgs/<uuid:org_id>/accounts/<uuid:pk>/",
        views.BankAccountDetailView.as_view(),
        name="account-detail",
    ),
    path(
        "orgs/<uuid:org_id>/accounts/<uuid:account_id>/deposits/",
        views.DepositView.as_view(),
        name="account-deposits",
    ),
    path(
        "orgs/<uuid:org_id>/accounts/<uuid:account_id>/transactions/",
        views.TransactionListView.as_view(),
        name="account-transactions",
    ),
    path(
        "orgs/<uuid:org_id>/accounts/<uuid:account_id>/statement.pdf",
        views.StatementView.as_view(),
        name="account-statement",
    ),
    path(
        "orgs/<uuid:org_id>/payments/",
        views.PaymentListCreateView.as_view(),
        name="payment-list",
    ),
    path(
        "orgs/<uuid:org_id>/payments/<uuid:pk>/",
        views.PaymentDetailView.as_view(),
        name="payment-detail",
    ),
    path(
        "orgs/<uuid:org_id>/payments/<uuid:pk>/cancel/",
        views.PaymentCancelView.as_view(),
        name="payment-cancel",
    ),
    path("orgs/<uuid:org_id>/cards/", views.CardListCreateView.as_view(), name="card-list"),
    path(
        "orgs/<uuid:org_id>/cards/<uuid:pk>/<str:action>/",
        views.CardStatusView.as_view(),
        name="card-status",
    ),
]
