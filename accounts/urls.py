"""Account/auth routes."""

from django.urls import path

from accounts import views

urlpatterns = [
    path("auth/register/", views.RegisterView.as_view(), name="auth-register"),
    path("auth/token/", views.LoginView.as_view(), name="token-obtain-pair"),
    path("me/", views.MeView.as_view(), name="me"),
    path(
        "orgs/<uuid:org_id>/members/",
        views.MemberListCreateView.as_view(),
        name="member-list",
    ),
    path(
        "orgs/<uuid:org_id>/members/<uuid:pk>/",
        views.MemberDetailView.as_view(),
        name="member-detail",
    ),
]
