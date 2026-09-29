from django.urls import path

from audit import views

urlpatterns = [
    path("orgs/<uuid:org_id>/audit/", views.AuditEventListView.as_view(), name="audit-list"),
]
