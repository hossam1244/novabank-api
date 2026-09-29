"""Audit trail API — admin/owner-only, read-only."""

from rest_framework import generics, permissions

from audit.models import AuditEvent


class AuditEventListView(generics.ListAPIView):
    """GET /api/v1/orgs/{org_id}/audit — the organization's audit trail."""

    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = None  # set below to avoid an import cycle at module load

    def get_serializer_class(self):
        from audit.serializers import AuditEventSerializer

        return AuditEventSerializer

    def get_queryset(self):
        from rest_framework import exceptions

        from accounts.models import Membership

        membership = self.request.user.memberships.filter(
            organization_id=self.kwargs["org_id"]
        ).first()
        if membership is None:
            raise exceptions.NotFound("Organization not found.")
        if not membership.at_least(Membership.Role.ADMIN):
            return AuditEvent.objects.none()
        qs = (
            AuditEvent.objects.filter(organization=membership.organization)
            .select_related("user")
            .order_by("-created_at")
        )
        action = self.request.query_params.get("action")
        if action:
            qs = qs.filter(action=action)
        return qs
