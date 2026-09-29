"""Organization-scoped permissions.

Every banking object carries an `organization` foreign key. List views filter
by the requester's memberships; object access re-checks the org so a member of
org A can never read org B's data even with a valid token.
"""

from rest_framework.permissions import SAFE_METHODS, BasePermission

from accounts.models import Membership


def membership_for(user, obj_org) -> Membership | None:
    """Return the requester's membership in the object's organization."""
    if user.is_anonymous:
        return None
    return (
        Membership.objects.filter(user=user, organization_id=obj_org.pk)
        .select_related("organization")
        .first()
    )


class IsOrgMember(BasePermission):
    """Allow only if the requester belongs to the object's organization."""

    message = "You are not a member of this organization."

    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        membership = membership_for(request.user, obj.organization)
        return membership is not None


class OrgRoleRequired(BasePermission):
    """Allow only if the requester's role meets the demanded minimum.

    Usage: `permission_classes = [..., OrgRoleRequired]` with the view
    attribute `min_role = Membership.Role.ADMIN`.
    """

    message = "Your role does not allow this action."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True  # read access is handled by IsOrgMember / queryset scoping
        min_role = getattr(view, "min_role", Membership.Role.ADMIN)
        org_id = view.kwargs.get("org_id")
        membership = Membership.objects.filter(user=request.user, organization_id=org_id).first()
        return membership is not None and membership.at_least(min_role)

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        min_role = getattr(view, "min_role", Membership.Role.ADMIN)
        membership = membership_for(request.user, obj.organization)
        return membership is not None and membership.at_least(min_role)
