from rest_framework import serializers

from audit.models import AuditEvent


class AuditEventSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True, default=None)

    class Meta:
        model = AuditEvent
        fields = (
            "id",
            "action",
            "target_type",
            "target_id",
            "user_email",
            "ip",
            "metadata",
            "created_at",
        )
