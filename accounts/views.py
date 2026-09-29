"""Auth and member-management views."""

from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from accounts.models import Membership
from accounts.permissions import IsOrgMember
from accounts.serializers import (
    MemberInviteResponseSerializer,
    MemberInviteSerializer,
    MembershipSerializer,
    MemberUpdateSerializer,
    OrganizationSerializer,
    RegisterResponseSerializer,
    RegisterSerializer,
    UserSerializer,
)
from audit.services import record_audit


class RegisterView(generics.CreateAPIView):
    """POST /api/v1/auth/register — create an organization with its owner."""

    permission_classes = (permissions.AllowAny,)
    serializer_class = RegisterSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = serializer.save()
        refresh = RefreshToken.for_user(result["user"])
        payload = {
            "refresh": str(refresh),
            "access": str(refresh.access_token),
            "user": UserSerializer(result["user"]).data,
            "organization": OrganizationSerializer(result["organization"]).data,
        }
        record_audit(
            request,
            organization=result["organization"],
            action="auth.registered",
            target=result["user"],
        )
        return Response(RegisterResponseSerializer(payload).data, status=status.HTTP_201_CREATED)


class LoginView(TokenObtainPairView):
    """POST /api/v1/auth/token — exchange email + password for a JWT pair."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"


class MeView(generics.RetrieveAPIView):
    """GET /api/v1/me — profile plus memberships and roles."""

    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user

    def retrieve(self, request, *args, **kwargs):
        user = self.get_object()
        memberships = Membership.objects.filter(user=user).select_related("organization", "user")
        return Response(
            {
                "user": UserSerializer(user).data,
                "memberships": MembershipSerializer(memberships, many=True).data,
            }
        )


class OrgMixin:
    """Load the organization from the URL once authentication has run.

    Runs in `initial()` — after DRF has authenticated the request — so
    anonymous callers get a clean 401 and non-members a 404.
    """

    def initial(self, request, *args, **kwargs):
        from rest_framework import exceptions

        membership = (
            request.user.memberships.filter(organization_id=kwargs.get("org_id"))
            .select_related("organization")
            .first()
        )
        if membership is None:
            raise exceptions.NotFound("Organization not found.")
        self.organization = membership.organization
        super().initial(request, *args, **kwargs)


class MemberListCreateView(OrgMixin, generics.ListCreateAPIView):
    """GET/POST /api/v1/orgs/{org_id}/members — manage team membership."""

    permission_classes = (permissions.IsAuthenticated,)

    def get_serializer_class(self):
        if self.request.method == "POST":
            return MemberInviteSerializer
        return MembershipSerializer

    def get_queryset(self):
        return (
            Membership.objects.filter(organization=self.organization)
            .select_related("user", "organization")
            .order_by("created_at")
        )

    def create(self, request, *args, **kwargs):
        # Only admins and owners may invite members — enforced before the
        # serializer runs so no user is ever created by an unauthorized call.
        membership = request.user.memberships.filter(organization=self.organization).first()
        if membership is None or not membership.at_least(Membership.Role.ADMIN):
            self.permission_denied(self.request, message="Admin role required to invite members.")
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = serializer.save()
        record_audit(
            request,
            organization=self.organization,
            action="member.added",
            target=result["membership"],
            metadata={"role": result["membership"].role},
        )
        payload = {
            "membership": MembershipSerializer(result["membership"]).data,
            "temp_password": result["temp_password"],
        }
        if result["temp_password"] is None:
            payload.pop("temp_password")
        return Response(
            MemberInviteResponseSerializer(payload).data, status=status.HTTP_201_CREATED
        )


class MemberDetailView(OrgMixin, generics.RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE /api/v1/orgs/{org_id}/members/{id}."""

    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = MemberUpdateSerializer
    http_method_names = ("get", "patch", "delete")

    def get_serializer_class(self):
        return MembershipSerializer if self.request.method == "GET" else MemberUpdateSerializer

    def get_queryset(self):
        return Membership.objects.filter(organization=self.organization).select_related(
            "user", "organization"
        )

    def get_actor_membership(self):
        return self.request.user.memberships.filter(organization=self.organization).first()

    def patch(self, request, *args, **kwargs):
        actor = self.get_actor_membership()
        if actor is None or actor.role != Membership.Role.OWNER:
            return Response(
                {
                    "error": {
                        "code": "permission_denied",
                        "message": "Only an owner can change roles.",
                        "details": {},
                    }
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().patch(request, *args, **kwargs)

    def delete(self, request, *args, **kwargs):
        actor = self.get_actor_membership()
        instance = self.get_object()
        if actor is None or not actor.at_least(Membership.Role.ADMIN):
            return Response(
                {
                    "error": {
                        "code": "permission_denied",
                        "message": "Admin role required to remove members.",
                        "details": {},
                    }
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        if instance.role == Membership.Role.OWNER:
            return Response(
                {
                    "error": {
                        "code": "permission_denied",
                        "message": "Owners cannot be removed. Demote them first.",
                        "details": {},
                    }
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        record_audit(
            request, organization=self.organization, action="member.removed", target=instance
        )
        return super().delete(request, *args, **kwargs)


__all__ = (
    "RegisterView",
    "LoginView",
    "MeView",
    "MemberListCreateView",
    "MemberDetailView",
    "IsOrgMember",
)
