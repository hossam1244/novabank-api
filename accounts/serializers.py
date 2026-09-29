"""Serializers for auth and member management."""

from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import serializers

from accounts.models import Membership, Organization

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "email", "first_name", "last_name", "date_joined")
        read_only_fields = ("id", "email", "date_joined")


class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ("id", "name", "created_at")
        read_only_fields = ("id", "created_at")


class MembershipSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    organization = OrganizationSerializer(read_only=True)

    class Meta:
        model = Membership
        fields = ("id", "user", "organization", "role", "created_at")
        read_only_fields = ("id", "created_at")


class RegisterSerializer(serializers.Serializer):
    """Self-service onboarding: creates the organization and its owner."""

    email = serializers.EmailField()
    password = serializers.CharField(
        min_length=10, write_only=True, style={"input_type": "password"}
    )
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    organization_name = serializers.CharField(max_length=200)

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value.lower()

    @transaction.atomic
    def create(self, validated_data):
        from banking.services import ensure_organization_defaults

        user = User.objects.create_user(
            email=validated_data["email"],
            password=validated_data["password"],
            first_name=validated_data["first_name"],
            last_name=validated_data["last_name"],
        )
        organization = Organization.objects.create(name=validated_data["organization_name"])
        Membership.objects.create(user=user, organization=organization, role=Membership.Role.OWNER)
        ensure_organization_defaults(organization)
        return {"user": user, "organization": organization}


class RegisterResponseSerializer(serializers.Serializer):
    """Documents the response of registration (tokens + profile)."""

    refresh = serializers.CharField()
    access = serializers.CharField()
    user = UserSerializer()
    organization = OrganizationSerializer()


class MemberInviteSerializer(serializers.Serializer):
    """Invite a member by email.

    Demo simplification: if the user does not exist yet, one is created and a
    temporary password is returned once, in this response. A production
    system would send an email invitation with a set-password link instead.
    """

    email = serializers.EmailField()
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    role = serializers.ChoiceField(
        choices=Membership.Role.choices, default=Membership.Role.EMPLOYEE
    )

    def validate_role(self, value):
        # Only an owner may create another owner.
        if value == Membership.Role.OWNER:
            request = self.context["request"]
            membership = request.user.memberships.filter(
                organization_id=self.context["view"].kwargs["org_id"]
            ).first()
            if membership is None or membership.role != Membership.Role.OWNER:
                raise serializers.ValidationError("Only an owner can grant the owner role.")
        return value

    def validate(self, attrs):
        email = attrs["email"].lower()
        existing = User.objects.filter(email__iexact=email).first()
        attrs["existing_user"] = existing
        if existing is not None:
            org_id = self.context["view"].kwargs["org_id"]
            if Membership.objects.filter(user=existing, organization_id=org_id).exists():
                raise serializers.ValidationError(
                    "This user is already a member of the organization."
                )
        attrs["email"] = email
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        from django.contrib.auth.password_validation import validate_password

        organization = self.context["view"].organization
        user = validated_data.get("existing_user")
        temp_password = None
        if user is None:
            import secrets

            temp_password = secrets.token_urlsafe(12)
            validate_password(temp_password)
            user = User.objects.create_user(
                email=validated_data["email"],
                password=temp_password,
                first_name=validated_data["first_name"],
                last_name=validated_data["last_name"],
            )
        membership = Membership.objects.create(
            user=user,
            organization=organization,
            role=validated_data["role"],
        )
        return {"membership": membership, "temp_password": temp_password}


class MemberInviteResponseSerializer(serializers.Serializer):
    membership = MembershipSerializer()
    temp_password = serializers.CharField(
        required=False,
        help_text="Only present when a new user was created. Never shown again.",
    )


class MemberUpdateSerializer(serializers.ModelSerializer):
    """Role updates — owner-only, with last-owner protection."""

    class Meta:
        model = Membership
        fields = ("role",)

    def validate_role(self, value):
        if value not in (Membership.Role.OWNER, Membership.Role.ADMIN, Membership.Role.EMPLOYEE):
            raise serializers.ValidationError("Unknown role.")
        if value == Membership.Role.OWNER:
            request = self.context["request"]
            actor = request.user.memberships.filter(
                organization_id=self.instance.organization_id
            ).first()
            if actor is None or actor.role != Membership.Role.OWNER:
                raise serializers.ValidationError("Only an owner can grant the owner role.")
        return value

    def update(self, instance, validated_data):
        demoting_last_owner = (
            instance.role == Membership.Role.OWNER
            and validated_data.get("role") != Membership.Role.OWNER
        )
        if demoting_last_owner:
            other_owners = (
                Membership.objects.filter(
                    organization_id=instance.organization_id, role=Membership.Role.OWNER
                )
                .exclude(pk=instance.pk)
                .exists()
            )
            if not other_owners:
                raise serializers.ValidationError("An organization must keep at least one owner.")
        return super().update(instance, validated_data)
